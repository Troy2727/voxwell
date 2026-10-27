/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Supabase project for accounts; both unset means the app runs without sign-in.
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
}
