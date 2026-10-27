import { useEffect, useState } from 'react';
import { createClient, type Session } from '@supabase/supabase-js';
import { toast } from 'sonner';

const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

/** Null when the build has no Supabase project set: the app then opens straight to the dashboard. */
export const supabase = url && key ? createClient(url, key, { auth: { flowType: 'pkce' } }) : null;

/** Where links in account emails and Google sign-in return to. The desktop app registers voxwell://. */
export const redirectTo = () => (window.voxwell ? 'voxwell://auth/callback' : window.location.origin);

/** Whether the project has Google sign-in turned on; the sign-in page hides the button otherwise. */
export async function googleEnabled(): Promise<boolean> {
  const res = await fetch(`${url}/auth/v1/settings`, { headers: { apikey: key! } });
  return res.ok && (await res.json()).external?.google === true;
}

/** Finish a sign-in from a voxwell://auth/callback link (the browser build does this itself from its URL). */
async function finishFromLink(link: string) {
  const { searchParams, hash } = new URL(link);
  const params = new URLSearchParams([...searchParams, ...new URLSearchParams(hash.slice(1))]);
  const failure = params.get('error_description');
  if (failure) throw new Error(failure);
  const code = params.get('code');
  if (!code) return;
  const { error } = await supabase!.auth.exchangeCodeForSession(code);
  if (error) throw error;
}

/**
 * The signed-in session: undefined while loading, null when signed out (or accounts are off).
 * `recovering` is true after a password-reset link, until the user sets a new password.
 */
export function useSession() {
  const [session, setSession] = useState<Session | null | undefined>(supabase ? undefined : null);
  const [recovering, setRecovering] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((event, next) => {
      setSession(next);
      if (event === 'PASSWORD_RECOVERY') setRecovering(true);
    });
    const stopLinks = window.voxwell?.auth.onCallback((link) =>
      finishFromLink(link).catch((e: Error) => toast.error(`Sign-in failed: ${e.message}`)),
    );
    return () => {
      data.subscription.unsubscribe();
      stopLinks?.();
    };
  }, []);

  return { session, recovering, endRecovery: () => setRecovering(false) };
}
