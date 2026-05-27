import { useEffect } from 'react';
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';
import { cn } from '../lib/utils';

export function Toast({ message, type = 'info', onClose, duration = 5000 }) {
    useEffect(() => {
        if (duration > 0) {
            const timer = setTimeout(onClose, duration);
            return () => clearTimeout(timer);
        }
    }, [duration, onClose]);

    const bgColor = {
        success: 'border-primary/25 bg-card text-foreground',
        error: 'border-destructive/25 bg-card text-foreground',
        warning: 'border-accent/80 bg-card text-foreground',
        info: 'border-info/25 bg-card text-foreground'
    }[type];

    const iconColor = {
        success: 'text-primary',
        error: 'text-destructive',
        warning: 'text-accent-foreground',
        info: 'text-info'
    }[type];

    const icon = {
        success: <CheckCircle2 className="w-5 h-5" />,
        error: <AlertTriangle className="w-5 h-5" />,
        warning: <AlertTriangle className="w-5 h-5" />,
        info: <Info className="w-5 h-5" />
    }[type];

    return (
        <div className={cn(
            "fixed right-4 top-4 z-50 flex max-w-md items-center gap-3 rounded-2xl border px-4 py-3 shadow-[0_18px_60px_hsl(218_30%_12%/0.14)] animate-in fade-in slide-in-from-right",
            bgColor
        )}>
            <span className={iconColor}>{icon}</span>
            <span className="text-sm font-semibold">{message}</span>
            <button onClick={onClose} className="ml-2 rounded-lg p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Close notification">
                <X className="w-4 h-4" />
            </button>
        </div>
    );
}
