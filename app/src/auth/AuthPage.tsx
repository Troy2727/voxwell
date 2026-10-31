import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowRight, Eye, EyeOff, Loader2, Lock, Mic, SlidersHorizontal, Type, Video } from 'lucide-react';
import { toast } from 'sonner';
import { LogoMark } from '@/components/logo';
import { ErrorAlert, Field, message } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { googleEnabled, redirectTo, supabase } from '@/lib/auth';
import { WaveStage } from './wave-stage';

const TOOLS = [
  { icon: Mic, label: 'Clone' },
  { icon: SlidersHorizontal, label: 'Design' },
  { icon: Video, label: 'Dub' },
  { icon: Type, label: 'Dictate' },
];

function GoogleIcon() {
  // Google's logo colors, required by its brand guidelines.
  return (
    <svg viewBox="0 0 48 48" aria-hidden className="size-5">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function PasswordInput({ id, autoComplete, value, onChange }: { id: string; autoComplete: string; value: string; onChange: (v: string) => void }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input id={id} type={shown ? 'text' : 'password'} autoComplete={autoComplete} required minLength={6} placeholder="Enter your password" className="h-11 pr-11" value={value} onChange={(e) => onChange(e.target.value)} />
      <Button type="button" variant="ghost" size="icon" className="text-muted-foreground absolute top-1/2 right-1 -translate-y-1/2" aria-label={shown ? 'Hide password' : 'Show password'} aria-pressed={shown} onClick={() => setShown(!shown)}>
        {shown ? <EyeOff /> : <Eye />}
      </Button>
    </div>
  );
}

function SubmitButton({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <Button type="submit" size="lg" className="h-11 w-full font-semibold" disabled={busy}>
      {busy ? <Loader2 className="animate-spin" /> : null}
      {children}
      {busy ? null : <ArrowRight />}
    </Button>
  );
}

/**
 * Sign in only: accounts are created by the owner in Supabase, which also has sign-up turned off.
 * Google sign-in stays for accounts that already exist. Signing in opens the dashboard.
 */
function AccountForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [google, setGoogle] = useState(false);

  useEffect(() => {
    googleEnabled().then(setGoogle, () => setGoogle(false));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { error } = await supabase!.auth.signInWithPassword({ email, password });
      if (error) throw error;
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function signInWithGoogle() {
    setBusy(true);
    setError('');
    try {
      const desktop = !!window.voxwell;
      const { data, error } = await supabase!.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: redirectTo(), skipBrowserRedirect: desktop } });
      if (error) throw error;
      if (desktop) {
        await window.voxwell!.auth.openExternal(data.url);
        toast('Finish signing in with Google in your browser.');
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <div className="mb-10 flex items-center justify-center gap-3">
        <LogoMark className="size-14" />
        <span className="text-3xl font-bold tracking-tight">Voxwell</span>
      </div>
      <h1 className="text-center text-3xl font-bold tracking-tight">Welcome back</h1>
      <p className="text-muted-foreground mt-2 mb-8 text-center">Sign in with the login you were given</p>

      {google && (
        <>
          <Button type="button" variant="outline" size="lg" className="h-11 w-full font-semibold" disabled={busy} onClick={signInWithGoogle}>
            <GoogleIcon />
            Continue with Google
          </Button>
          <div className="text-muted-foreground my-6 flex items-center gap-4 text-sm before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">or</div>
        </>
      )}
      <form className="flex flex-col gap-5" onSubmit={submit}>
        <Field label="Email address" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required placeholder="Enter your email" className="h-11" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <PasswordInput id="password" autoComplete="current-password" value={password} onChange={setPassword} />
        </Field>
        <ErrorAlert message={error} />
        <SubmitButton busy={busy}>Sign in</SubmitButton>
      </form>
      <p className="text-muted-foreground mt-6 text-center text-sm">Accounts are by invitation only.</p>
      <p className="text-muted-foreground mt-8 flex items-center justify-center gap-2 text-xs">
        <Lock className="size-3.5" />
        Your voices stay on your device.
      </p>
    </div>
  );
}

/** Shown after a password-reset link: set the new password, then the dashboard opens. */
function NewPasswordForm({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const { error } = await supabase!.auth.updateUser({ password });
    setBusy(false);
    if (error) return setError(error.message);
    toast.success('Password updated.');
    onDone();
  }

  return (
    <div className="w-full max-w-sm">
      <h1 className="text-center text-3xl font-bold tracking-tight">Set a new password</h1>
      <p className="text-muted-foreground mt-2 mb-8 text-center">Choose the password you'll sign in with from now on.</p>
      <form className="flex flex-col gap-5" onSubmit={submit}>
        <Field label="New password" htmlFor="password" hint="At least 6 characters.">
          <PasswordInput id="password" autoComplete="new-password" value={password} onChange={setPassword} />
        </Field>
        <ErrorAlert message={error} />
        <SubmitButton busy={busy}>Save password</SubmitButton>
      </form>
    </div>
  );
}

export function AuthPage({ recovering, onRecovered }: { recovering: boolean; onRecovered: () => void }) {
  return (
    <main className="min-h-svh p-4 md:p-10">
      <div className="bg-card mx-auto grid max-w-6xl overflow-hidden rounded-2xl border lg:grid-cols-2">
        <section className="flex justify-center px-5 py-12 md:px-16 md:py-14">
          {recovering ? <NewPasswordForm onDone={onRecovered} /> : <AccountForm />}
        </section>
        <aside aria-label="About Voxwell" className="flex flex-col gap-7 border-t px-5 py-12 md:px-12 md:py-14 lg:border-t-0 lg:border-l">
          <h2 className="text-4xl leading-tight font-bold tracking-tight md:text-5xl">
            Your Voice.{' '}
            <span className="text-primary dark:from-cta-from dark:via-cta-via dark:to-cta-to dark:bg-linear-90 dark:bg-clip-text dark:text-transparent">Every Language.</span>
          </h2>
          <p className="text-muted-foreground max-w-md text-lg">Clone, design and dub voices, all running on your own machine.</p>
          <WaveStage />
          <p className="text-xl font-bold tracking-wide uppercase">
            <span className="text-primary">4 tools.</span> One studio.
          </p>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {TOOLS.map(({ icon: Icon, label }) => (
              <li key={label} className="bg-secondary flex flex-col items-center gap-2.5 rounded-xl border px-2 py-4 text-sm font-semibold">
                <Icon className="text-primary size-7" />
                {label}
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </main>
  );
}
