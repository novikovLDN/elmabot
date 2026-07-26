import { endpoints } from "./api";

function urlB64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** Subscribe this device to admin web-push. Throws with a readable message. */
export async function enablePush(): Promise<void> {
  if (!pushSupported()) throw new Error("Браузер не поддерживает push");
  const key = await endpoints.pushKey();
  if (!key.enabled || !key.public_key) throw new Error("Push выключен на сервере (нет VAPID-ключей)");

  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Нет разрешения на уведомления");

  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(key.public_key),
    });
  }
  await endpoints.pushSubscribe(sub.toJSON());
}

export async function disablePush(): Promise<void> {
  if (!pushSupported()) return;
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await endpoints.pushUnsubscribe(sub.endpoint);
    await sub.unsubscribe();
  }
}

export async function pushSubscribed(): Promise<boolean> {
  if (!pushSupported()) return false;
  const reg = await navigator.serviceWorker.ready;
  return !!(await reg.pushManager.getSubscription());
}
