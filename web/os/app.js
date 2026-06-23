if (!labels.length) {
        ctx.parentElement.innerHTML += '<div class="empty-desc" style="margin-top:8px;">No activity yet</div>';
        return;
    }
    
    state.chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: 'rgba(118, 185, 0, 0.3)',
                borderColor: 'rgba(118, 185, 0, 0.8)',
                borderWidth: 1,
                borderRadius: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', font: { size: 10 } } },
                y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#71717a', font: { size: 10 } } },
            },
        },
    });