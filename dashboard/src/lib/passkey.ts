import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { endpoints } from "./api";
import { setToken } from "./auth";

// Derive the option types from the lib's function signatures (v11 takes
// `{ optionsJSON }`) so we don't depend on @simplewebauthn/types directly.
type RegOptions = Parameters<typeof startRegistration>[0]["optionsJSON"];
type AuthOptions = Parameters<typeof startAuthentication>[0]["optionsJSON"];

/** Register a new passkey for the signed-in admin. */
export async function registerPasskey(label?: string): Promise<void> {
  const optionsJSON = (await endpoints.passkeyRegisterBegin()) as unknown as RegOptions;
  const att = await startRegistration({ optionsJSON });
  await endpoints.passkeyRegisterComplete(att, label);
}

/** Sign in with a passkey; stores the JWT on success. */
export async function loginPasskey(): Promise<void> {
  const { flow_id, options } = await endpoints.passkeyLoginBegin();
  const asr = await startAuthentication({ optionsJSON: options as unknown as AuthOptions });
  const res = await endpoints.passkeyLoginComplete(flow_id, asr);
  setToken(res.token);
}
