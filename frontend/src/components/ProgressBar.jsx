export function ProgressBar({ completed, total, duration }) {
    const safeCompleted = Number.isFinite(Number(completed)) ? Math.max(0, Number(completed)) : 0;
    const safeTotal = Number.isFinite(Number(total)) ? Math.max(0, Number(total)) : 0;
    const safeDuration = Number.isFinite(Number(duration)) ? Math.max(0, Number(duration)) : 0;
    const rawPercentage = safeTotal > 0 ? Math.round((safeCompleted / safeTotal) * 100) : 0;
    const percentage = Math.min(100, Math.max(0, rawPercentage));
    const proxiesPerSecond = safeDuration > 0 ? (safeCompleted / safeDuration).toFixed(1) : '0.0';

    return (
        <div className="panel-subtle rounded-2xl p-4">
            <div className="flex justify-between text-sm font-semibold">
                <span className="text-foreground">
                    Checking {safeCompleted}/{safeTotal}
                </span>
                <span className="text-primary">
                    {percentage}%
                </span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                <div
                    className="h-full rounded-full bg-primary transition-all duration-300"
                    style={{ width: `${percentage}%` }}
                />
            </div>
            <div className="mt-3 flex justify-between text-xs text-muted-foreground">
                <span>{proxiesPerSecond} proxies/sec</span>
                <span>{safeDuration.toFixed(1)}s elapsed</span>
            </div>
        </div>
    );
}
