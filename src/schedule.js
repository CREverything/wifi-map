export const PERIOD = 5 * 60 * 1000;
export const nextBoundary = now => (Math.floor(now / PERIOD) + 1) * PERIOD;
