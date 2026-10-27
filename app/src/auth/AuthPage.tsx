import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowRight, Eye, EyeOff, Loader2, Lock, MailCheck, Mic, SlidersHorizontal, Type, Video } from 'lucide-react';
import { toast } from 'sonner';
import { ErrorAlert, Field, message } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { googleEnabled, redirectTo, supabase } from '@/lib/auth';
import { WaveStage } from './wave-stage';

type Mode = 'signin' | 'signup' | 'forgot' | 'sent';

const COPY: Record<Mode, { title: string; sub: string; button?: string }> = {
  signin: { title: 'Welcome back', sub: 'Sign in to your studio', button: 'Sign in' },
  signup: { title: 'Join the studio', sub: 'Create your account and start creating voices', button: 'Create account' },
  forgot: { title: 'Reset your password', sub: "We'll email you a link to set a new one", button: 'Send reset link' },
  sent: { title: 'Check your email', sub: '' },
};

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

/** Sign in, create an account, or reset a forgotten password. Signing in opens the dashboard. */
function AccountForm() {
  const [mode, setMode] = useState<Mode>('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sentTo, setSentTo] = useState('');
  const [google, setGoogle] = useState(false);

  useEffect(() => {
    googleEnabled().then(setGoogle, () => setGoogle(false));
  }, []);

  const go = (next: Mode) => {
    setMode(next);
    setError('');
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (mode === 'signin') {
        const { error } = await supabase!.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else if (mode === 'signup') {
        const { data, error } = await supabase!.auth.signUp({ email, password, options: { data: { full_name: name.trim() }, emailRedirectTo: redirectTo() } });
        if (error) throw error;
        // With email confirmation on, there is no session until the link in the email is opened.
        if (!data.session) {
          setSentTo(`We sent a confirmation link to ${email}. Open it to finish creating your account.`);
          go('sent');
        }
      } else {
        const { error } = await supabase!.auth.resetPasswordForEmail(email, { redirectTo: redirectTo() });
        if (error) throw error;
        setSentTo(`If ${email} has an account, a link to reset its password is on its way.`);
        go('sent');
      }
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

  const copy = COPY[mode];
  return (
    <div className="w-full max-w-sm">
      <div className="mb-10 flex items-center justify-center gap-3">
        <img src="favicon.svg" alt="" className="size-11" />
        <span className="text-2xl font-bold tracking-tight">Voxwell</span>
      </div>
      <h1 className="text-center text-3xl font-bold tracking-tight">{copy.title}</h1>
      <p className="text-muted-foreground mt-2 mb-8 text-center">{mode === 'sent' ? sentTo : copy.sub}</p>

      {mode === 'sent' ? (
        <div className="flex flex-col items-center gap-6">
          <MailCheck className="text-primary size-10" />
          <Button variant="outline" onClick={() => go('signin')}>Back to sign in</Button>
        </div>
      ) : (
        <>
          {google && mode !== 'forgot' && (
            <>
              <Button type="button" variant="outline" size="lg" className="h-11 w-full font-semibold" disabled={busy} onClick={signInWithGoogle}>
                <GoogleIcon />
                Continue with Google
              </Button>
              <div className="text-muted-foreground my-6 flex items-center gap-4 text-sm before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">or</div>
            </>
          )}
          <form className="flex flex-col gap-5" onSubmit={submit}>
            {mode === 'signup' && (
              <Field label="Name" htmlFor="name">
                <Input id="name" autoComplete="name" placeholder="Enter your name" className="h-11" value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
            )}
            <Field label="Email address" htmlFor="email">
              <Input id="email" type="email" autoComplete="email" required placeholder="Enter your email" className="h-11" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            {mode !== 'forgot' && (
              <Field label="Password" htmlFor="password" hint={mode === 'signup' ? 'At least 6 characters.' : undefined}>
                <PasswordInput id="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} value={password} onChange={setPassword} />
              </Field>
            )}
            {mode === 'signin' && (
              <button type="button" className="text-muted-foreground hover:text-foreground -mt-2 self-end text-sm" onClick={() => go('forgot')}>
                Forgot password?
              </button>
            )}
            <ErrorAlert message={error} />
            <SubmitButton busy={busy}>{copy.button}</SubmitButton>
          </form>
          <p className="text-muted-foreground mt-6 text-center text-sm">
            {mode === 'signin' ? 'New to Voxwell?' : mode === 'signup' ? 'Already have an account?' : 'Remembered it?'}{' '}
            <button type="button" className="text-primary font-semibold underline-offset-4 hover:underline" onClick={() => go(mode === 'signin' ? 'signup' : 'signin')}>
              {mode === 'signin' ? 'Create an account' : 'Sign in'}
            </button>
          </p>
        </>
      )}
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
            Your Voice. <span className="text-primary">Every Language.</span>
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
