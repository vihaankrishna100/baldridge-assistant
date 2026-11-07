"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken, setToken } from "./api";

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: "staff" | "leadership" | "admin" | "team";
  totp_confirmed: boolean;
  twofa_method?: "" | "app" | "email";
  is_active: boolean;
  last_login_at?: string | null;
  permissions?: Permission[];
};

/** Set per role on the Admin page; the server enforces them on every request. */
export type Permission =
  | "ask"
  | "see_leadership_docs"
  | "view_documents"
  | "download"
  | "manage_documents";

export function can(user: User | null | undefined, permission: Permission): boolean {
  if (!user) return false;
  if (user.role === "admin") return true;
  return (user.permissions ?? []).includes(permission);
}

/** Where to send someone after sign-in: the first page their role can use. */
export function homePath(user: User | null | undefined): string {
  if (can(user, "ask")) return "/ask";
  if (can(user, "view_documents")) return "/documents";
  if (user?.role === "admin") return "/admin";
  return "/no-access";
}

type AuthValue = {
  user: User | null;
  loading: boolean;
  signIn: (token: string, user: User) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const settled = useRef(false);
  const router = useRouter();

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api<User>("/auth/me"));
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Skip the verification round trip when signIn already gave us the user.
    if (settled.current) return;
    void refresh();
  }, [refresh]);

  const signIn = useCallback((token: string, nextUser: User) => {
    setToken(token);
    setUser(nextUser);
    // The login response already carried the full user, so the mount effect's
    // /auth/me call would be a second round trip for data we hold. Marking the
    // session as settled skips it.
    setLoading(false);
    settled.current = true;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      /* the local session is cleared regardless */
    }
    setToken(null);
    setUser(null);
    settled.current = false;
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Redirects to /login when there is no session, and to the person's home
 * page when their role lacks what this page needs ("admin" or a permission). */
export function useRequireAuth(requirement?: "admin" | Permission) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const allowed =
    !!user &&
    (requirement === undefined ||
      (requirement === "admin" ? user.role === "admin" : can(user, requirement)));

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (!allowed) router.replace(homePath(user));
  }, [user, loading, allowed, router]);

  // Until the redirect lands, pages render their loading state rather than
  // flashing content the role can't use.
  return { user: allowed ? user : null, loading: loading || (!!user && !allowed) };
}
