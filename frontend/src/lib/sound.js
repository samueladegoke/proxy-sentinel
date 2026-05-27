export class SoundNotifier {
    constructor() {
        this.audioContext = null;
        this.enabled = true;
        this.frequency = 800;
        this.duration = 200;
        this.volume = 0.5;
    }

    init() {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        return this.audioContext;
    }

    play(frequency = null, duration = null) {
        if (!this.enabled) return;

        try {
            const ctx = this.init();
            const oscillator = ctx.createOscillator();
            const gainNode = ctx.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(ctx.destination);

            oscillator.frequency.value = frequency ?? this.frequency;
            oscillator.type = 'sine';

            gainNode.gain.setValueAtTime(this.volume, ctx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + (duration ?? this.duration) / 1000);

            oscillator.start(ctx.currentTime);
            oscillator.stop(ctx.currentTime + (duration ?? this.duration) / 1000);
        } catch (e) {
            console.error('Failed to play sound:', e);
        }
    }

    playAlert() {
        this.play(880, 150);
        setTimeout(() => this.play(988, 150), 200);
        setTimeout(() => this.play(1175, 300), 400);
    }

    setEnabled(enabled) {
        this.enabled = enabled;
    }

    setVolume(volume) {
        this.volume = Math.max(0, Math.min(1, volume));
    }

    setFrequency(frequency) {
        this.frequency = frequency;
    }

    setDuration(duration) {
        this.duration = duration;
    }
}

export const soundNotifier = new SoundNotifier();
