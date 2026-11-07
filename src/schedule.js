export const COLLECTION_PERIOD_MS = 5 * 60 * 1000;

/** The next wall-clock five-minute boundary (:00, :05, …) strictly after `now`. */
export const nextCollectionTime = (now) => (Math.floor(now / COLLECTION_PERIOD_MS) + 1) * COLLECTION_PERIOD_MS;
