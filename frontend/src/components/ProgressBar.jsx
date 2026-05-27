export function ProgressBar({ completed, total, duration }) {
    const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;
    const proxiesPerSecond = duration > 0 ? (completed / duration).toFixed(1) : 0;

    return (
        <div className="panel-subtle rounded-2xl p-4">
            <div className="flex justify-between text-sm font-semibold">
                <span className="text-foreground">
                    Checking {completed}/{total}
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
                <span>{duration.toFixed(1)}s elapsed</span>
            </div>
        </div>
    );
}
