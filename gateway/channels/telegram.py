from __future__ import annotations

import html
import logging
import time
from typing import TYPE_CHECKING

from gateway.channels.base import BaseChannelAdapter, chunk_text
from gateway.types import ChannelKind, InboundMessage

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)

_APPROVE_CB = "nexus:approve"
_CANCEL_CB = "nexus:cancel"


class TelegramChannel(BaseChannelAdapter):
    name = ChannelKind.TELEGRAM.value

    def __init__(self, gateway: NexusGateway, token: str):
        super().__init__(gateway)
        self.token = token
        self._app = None
        self._pending_approvals: dict[str, dict] = {}

    async def start(self) -> None:
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
            from telegram.ext import (
                Application, CallbackQueryHandler, CommandHandler,
                ContextTypes, MessageHandler, filters,
            )
        except ImportError as exc:
            raise RuntimeError("python-telegram-bot is required for Telegram. pip install python-telegram-bot") from exc

        async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            await update.message.reply_text(
                "\U0001f44b NEXUS-01 online.\n\n"
                "Send research, analysis, or exec requests.\n\n"
                "Commands:\n"
                "/help \u2014 capabilities\n"
                "/status \u2014 bot health\n"
                "/pending \u2014 show pending approvals\n\n"
                "Examples:\n"
                "\u2022 osint AI agent frameworks 2026\n"
                "\u2022 research competitor X and assess risk\n"
                "\u2022 exec ls -la (requires approval)"
            )

        async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            await update.message.reply_text(
                "\U0001f6e0 NEXUS-01 channels\n\n"
                "\u2022 osint <query> \u2014 intelligence gathering\n"
                "\u2022 analyst <data> \u2014 pattern analysis\n"
                "\u2022 exec <cmd> \u2014 shell (approval required)\n"
                "\u2022 Natural language auto-routes\n\n"
                "Destructive commands require inline approval.\n"
                "Approvals expire after 5 minutes."
            )

        async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            pending = self.gateway.approvals.pending_count()
            status = f"\u2705 NEXUS-01 Telegram channel is online."
            if pending:
                status += f"\n\n\U0001f514 {pending} pending approval(s)."
            await update.message.reply_text(status)

        async def pending_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            user = update.effective_user
            if user and not self.is_user_allowed(str(user.id)):
                await update.message.reply_text("\u26d4 You are not authorized.")
                return
            history = self.gateway.approvals.recent_history(5)
            if not history:
                await update.message.reply_text("No recent approvals.")
                return
            lines = []
            for req in history:
                icon = "\u2705" if req.status.value == "approved" else "\u274c" if req.status.value == "denied" else "\u23f0"
                lines.append(f"{icon} `{req.action}` \u2014 {req.status.value}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.text:
                return
            user = update.effective_user
            chat_id = str(update.effective_chat.id)
            if user and not self.is_user_allowed(str(user.id)):
                await update.message.reply_text("\u26d4 You are not authorized.")
                return

            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            inbound = InboundMessage(
                channel=ChannelKind.TELEGRAM,
                session_id=chat_id,
                text=update.message.text.strip(),
                user_id=str(user.id) if user else "",
                metadata={
                    "telegram_chat_id": chat_id,
                    "telegram_username": user.username if user else "",
                    "telegram_message_id": str(update.message.message_id),
                },
            )

            start = time.monotonic()
            response = await self.gateway.handle(inbound)
            elapsed = int((time.monotonic() - start) * 1000)

            if response.requires_approval:
                self._pending_approvals[chat_id] = {
                    "approval_id": response.approval_id,
                    "created_at": time.monotonic(),
                    "text": inbound.text,
                }
                cmd_preview = inbound.text.split(maxsplit=1)[1][:60] if inbound.text.strip().lower().startswith("exec") else inbound.text[:60]
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("\u2705 Approve", callback_data=_APPROVE_CB),
                        InlineKeyboardButton("\u274c Cancel", callback_data=_CANCEL_CB),
                    ]
                ])
                approval_msg = (
                    f"\u26a0\ufe0f *Execution approval required*\n\n"
                    f"Command: `{cmd_preview}`\n"
                    f"Expires in 5 minutes.\n\n"
                    f"Approve?"
                )
                await self._reply(update.message.reply_text, approval_msg, reply_markup=keyboard)
            else:
                meta = f" ({elapsed}ms)" if elapsed > 1000 else ""
                await self._reply(update.message.reply_text, response.text)

        async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            query = update.callback_query
            if not query:
                return
            await query.answer()
            chat_id = str(update.effective_chat.id)
            approved = query.data == _APPROVE_CB

            pending = self._pending_approvals.pop(chat_id, None)
            approval_id = pending["approval_id"] if pending else ""

            inbound = InboundMessage(
                channel=ChannelKind.TELEGRAM,
                session_id=chat_id,
                text="yes" if approved else "no",
                user_id=str(update.effective_user.id) if update.effective_user else "",
                metadata={"approval_decision": approved, "approval_id": approval_id},
            )
            response = await self.gateway.handle(inbound)

            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

            icon = "\u2705 Approved" if approved else "\u274c Denied"
            try:
                await query.edit_message_text(f"{icon}\n\n{response.text[:4000]}", parse_mode="Markdown")
            except Exception:
                try:
                    safe = html.escape(response.text[:4000])
                    await query.edit_message_text(f"{icon}\n\n{safe}", parse_mode="HTML")
                except Exception:
                    await self._reply(query.message.reply_text, response.text)

        async def on_non_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if update.message:
                await update.message.reply_text("Please send a text message.")

        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(CommandHandler("start", start_cmd))
        self._app.add_handler(CommandHandler("help", help_cmd))
        self._app.add_handler(CommandHandler("status", status_cmd))
        self._app.add_handler(CommandHandler("pending", pending_cmd))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
        self._app.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, on_non_text))
        self._app.add_handler(CallbackQueryHandler(on_callback))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        if not self._app:
            return
        for chunk in chunk_text(text):
            await self._app.bot.send_message(chat_id=int(session_id), text=chunk)

    async def _reply(self, reply_fn, text: str, reply_markup=None) -> None:
        for i, chunk in enumerate(chunk_text(text)):
            markup = reply_markup if i == len(chunk_text(text)) - 1 else None
            try:
                await reply_fn(chunk, parse_mode="Markdown", reply_markup=markup)
            except Exception:
                safe = html.escape(chunk)
                try:
                    await reply_fn(safe, parse_mode="HTML", reply_markup=markup)
                except Exception:
                    await reply_fn(chunk, reply_markup=markup)
