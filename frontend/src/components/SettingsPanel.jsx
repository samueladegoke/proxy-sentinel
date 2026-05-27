import { X, Volume2, VolumeX, Bell } from 'lucide-react';
import { cn } from '../lib/utils';
import { soundNotifier } from '../lib/sound';

export function SettingsPanel({ settings, onSettingsChange, onClose }) {
    const updateSoundEnabled = (enabled) => {
        soundNotifier.setEnabled(enabled);
        onSettingsChange({ ...settings, soundEnabled: enabled });
    };

    const testSound = () => {
        soundNotifier.setEnabled(settings.soundEnabled);
        if (!settings.soundEnabled) return;
        soundNotifier.setVolume(settings.volume);
        soundNotifier.setFrequency(settings.frequency);
        soundNotifier.playAlert();
    };

    return (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 animate-in fade-in">
            <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md animate-in zoom-in-95">
                <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                    <h2 className="text-lg font-semibold">Notification Settings</h2>
                    <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="p-6 space-y-6">
                    {/* Sound Settings */}
                    <div className="space-y-4">
                        <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Sound</h3>

                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                {settings.soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
                                <span>Sound Alerts</span>
                            </div>
                            <button
                                onClick={() => updateSoundEnabled(!settings.soundEnabled)}
                                className={cn(
                                    "w-12 h-6 rounded-full transition-colors",
                                    settings.soundEnabled ? "bg-primary" : "bg-muted"
                                )}
                            >
                                <div className={cn(
                                    "w-5 h-5 rounded-full bg-white shadow transition-transform",
                                    settings.soundEnabled ? "translate-x-6" : "translate-x-0.5"
                                )} />
                            </button>
                        </div>

                        <div className="space-y-2">
                            <div className="flex justify-between text-sm">
                                <span>Volume</span>
                                <span>{Math.round(settings.volume * 100)}%</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                value={settings.volume * 100}
                                onChange={(e) => onSettingsChange({ ...settings, volume: e.target.value / 100 })}
                                className="w-full accent-primary"
                            />
                        </div>

                        <div className="space-y-2">
                            <div className="flex justify-between text-sm">
                                <span>Frequency (Hz)</span>
                                <span>{settings.frequency} Hz</span>
                            </div>
                            <input
                                type="range"
                                min="200"
                                max="2000"
                                value={settings.frequency}
                                onChange={(e) => onSettingsChange({ ...settings, frequency: Number(e.target.value) })}
                                className="w-full accent-primary"
                            />
                        </div>

                        <button
                            onClick={testSound}
                            disabled={!settings.soundEnabled}
                            className="w-full px-4 py-2 bg-muted rounded-md text-sm transition-colors hover:bg-muted/80 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            Test Sound
                        </button>
                    </div>

                    {/* Visual Settings */}
                    <div className="space-y-4">
                        <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Visual</h3>

                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <Bell className="w-4 h-4" />
                                <span>Toast Notifications</span>
                            </div>
                            <button
                                onClick={() => onSettingsChange({ ...settings, toastEnabled: !settings.toastEnabled })}
                                className={cn(
                                    "w-12 h-6 rounded-full transition-colors",
                                    settings.toastEnabled ? "bg-primary" : "bg-muted"
                                )}
                            >
                                <div className={cn(
                                    "w-5 h-5 rounded-full bg-white shadow transition-transform",
                                    settings.toastEnabled ? "translate-x-6" : "translate-x-0.5"
                                )} />
                            </button>
                        </div>
                    </div>

                    {/* Tracking Interval */}
                    <div className="space-y-4">
                        <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">Tracking</h3>

                        <div className="space-y-2">
                            <div className="flex justify-between text-sm">
                                <span>Check Interval</span>
                                <span>{settings.trackingInterval} minutes</span>
                            </div>
                            <input
                                type="range"
                                min="1"
                                max="60"
                                value={settings.trackingInterval}
                                onChange={(e) => onSettingsChange({ ...settings, trackingInterval: Number(e.target.value) })}
                                className="w-full accent-primary"
                            />
                        </div>
                    </div>
                </div>

                <div className="px-6 py-4 border-t border-border flex justify-end gap-3">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 bg-muted rounded-md text-sm hover:bg-muted/80 transition-colors"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
}
