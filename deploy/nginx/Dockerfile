FROM nginx:alpine

RUN apk add --no-cache certbot certbot-nginx

COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN mkdir -p /var/www/certbot

CMD ["sh", "-c", "nginx -g 'daemon off;' & sleep 2 && certbot certonly --webroot -w /var/www/certbot -d navos.online --non-interactive --agree-tos --email admin@navos.online --redirect && nginx -g 'daemon off;'"]
