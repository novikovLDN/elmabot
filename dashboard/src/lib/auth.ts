const KEY = "elma_admin_jwt";

export function getToken(): string | null {
  return localStorage.getItem(KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(KEY);
}
export function isLoggedIn(): boolean {
  return !!getToken();
}
export function logout(): void {
  clearToken();
  window.location.assign("/dashboard/");
}
