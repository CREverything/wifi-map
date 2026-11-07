import { validateModelResponse } from './data.js';

// Call from a future API/WebSocket handler. Keep model credentials on your backend.
// The UI currently uses JSON import; no network endpoint is assumed.
export function decodeModelResponse(payload) {
  return validateModelResponse(typeof payload === 'string' ? JSON.parse(payload) : payload);
}
