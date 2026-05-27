export function RiskBadge({ clean, failed }) {
    if (failed) {
        return (
            <div className="flex w-fit items-center gap-2 rounded-full border border-destructive/20 bg-destructive/10 px-3 py-1">
                <span className="h-1.5 w-1.5 rounded-full bg-destructive"></span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-destructive">Failed</span>
            </div>
        );
    }
    if (clean) {
        return (
            <div className="flex w-fit items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1">
                <span className="h-1.5 w-1.5 rounded-full bg-primary"></span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-primary">Clean</span>
            </div>
        );
    }
    return (
        <div className="flex w-fit items-center gap-2 rounded-full border border-accent/60 bg-accent/70 px-3 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-accent-foreground"></span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-accent-foreground">Review</span>
        </div>
    );
}
