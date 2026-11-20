// Page-local measurements shared by cards, drawer headers and rail rows.
/** @typedef {{execution: string, number: number, elapsed_ms: number, quiet_ms: number|null, frozen: boolean}} Duration */
/** @typedef {{sample: Duration, received: number, elapsed: number, quiet: number|null}} Measurement */
/** @type {Map<string, Measurement>} */
const measurements = new Map();

const delta = (measurement, now) => measurement.sample.frozen ? 0 : Math.max(0, now - measurement.received);

/** Receive a server projection once, at the response boundary; redraws only read it.
 * @param {Duration|null|undefined} sample
 */
export function receiveDuration(sample) {
  if (!sample) return;
  const previous = measurements.get(sample.execution);
  if (previous && (sample.number <= previous.sample.number || previous.sample.frozen)) return;
  const now = performance.now();
  let elapsed = sample.elapsed_ms;
  let quiet = sample.quiet_ms;
  if (previous && !sample.frozen) {
    elapsed = Math.max(elapsed, previous.elapsed + delta(previous, now));
    const command = sample.quiet_ms === null ? null : sample.elapsed_ms - sample.quiet_ms;
    const oldCommand = previous.sample.quiet_ms === null ? null : previous.sample.elapsed_ms - previous.sample.quiet_ms;
    if (quiet !== null && previous.quiet !== null && oldCommand !== null && command <= oldCommand) {
      quiet = Math.max(quiet, previous.quiet + delta(previous, now));
    }
  }
  measurements.set(sample.execution, { sample, received: now, elapsed, quiet });
}

/** @param {string} execution @returns {number|null} */
export function elapsedDuration(execution) {
  const measurement = measurements.get(execution);
  return measurement ? measurement.elapsed + delta(measurement, performance.now()) : null;
}

/** @param {string} execution @returns {number|null} */
export function quietDuration(execution) {
  const measurement = measurements.get(execution);
  return measurement?.quiet == null ? null : measurement.quiet + delta(measurement, performance.now());
}
