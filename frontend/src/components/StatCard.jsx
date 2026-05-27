export function StatCard({ title, value, icon, tone = 'info', helper }) {
    const toneClass = {
        primary: 'drop-shadow-[0_12px_24px_rgba(25,215,255,0.18)]',
        info: 'drop-shadow-[0_12px_24px_rgba(25,215,255,0.18)]',
        danger: 'drop-shadow-[0_12px_24px_rgba(240,117,94,0.18)]',
        neutral: 'drop-shadow-[0_12px_24px_rgba(210,170,50,0.16)]'
    }[tone] || 'drop-shadow-[0_12px_24px_rgba(25,215,255,0.18)]';

    return (
        <article className="dashboard-panel rounded-2xl p-5">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">{title}</p>
                    <div className="mt-3 text-3xl font-extrabold tracking-tight text-foreground">{value ?? '0'}</div>
                </div>
                <div className={`flex h-12 w-12 shrink-0 items-center justify-center overflow-visible p-0 ${toneClass}`}>
                    {icon}
                </div>
            </div>
            {helper && <p className="mt-4 text-sm text-muted-foreground">{helper}</p>}
        </article>
    );
}
