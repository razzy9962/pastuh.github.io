const MSK_OFFSET_SECONDS = 3 * 60 * 60;

/** Return the start of a candle bucket using Moscow time boundaries. */
export function mskBucket(time: number, seconds: number, sessionStartHour = 0): number {
  if (!Number.isFinite(time) || !Number.isFinite(seconds) || seconds <= 0) return time;
  const local = time + MSK_OFFSET_SECONDS;
  const sessionOffset = sessionStartHour * 60 * 60;
  return Math.floor((local - sessionOffset) / seconds) * seconds + sessionOffset - MSK_OFFSET_SECONDS;
}

/** Return the start of the ISO week using Moscow time boundaries. */
export function mskWeekBucket(time: number): number {
  const local = new Date((time + MSK_OFFSET_SECONDS) * 1000);
  const day = local.getUTCDay() || 7;
  local.setUTCHours(0, 0, 0, 0);
  local.setUTCDate(local.getUTCDate() - day + 1);
  return Math.floor(local.getTime() / 1000) - MSK_OFFSET_SECONDS;
}
