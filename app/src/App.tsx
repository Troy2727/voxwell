import { useEffect, useState } from 'react';
import type { User } from '@supabase/supabase-js';
import { LogOut, Moon, PlugZap, Sun } from 'lucide-react';
import { api } from './api';
import { AuthPage } from './auth/AuthPage';
import { FEATURES } from './features';
import { LogoMark } from '@/components/logo';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { supabase, useSession } from '@/lib/auth';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';

const GROUPS = [...new Set(FEATURES.map((f) => f.group))];

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const dark = theme === 'dark';
  return (
    <Button variant="ghost" size="icon" className="size-8" aria-label={dark ? 'Light mode' : 'Dark mode'} onClick={() => setTheme(dark ? 'light' : 'dark')}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

function Account({ user }: { user: User }) {
  const email = user.email ?? '';
  const name: string = user.user_metadata.full_name || email;
  return (
    <div className="flex items-center gap-2 px-1 group-data-[collapsible=icon]:justify-center">
      <span className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold group-data-[collapsible=icon]:hidden">
        {(name || '?')[0].toUpperCase()}
      </span>
      <div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
        <p className="truncate text-sm font-medium">{name}</p>
        {name !== email && <p className="text-muted-foreground truncate text-xs">{email}</p>}
      </div>
      <Button variant="ghost" size="icon" className="size-8" aria-label="Sign out" title="Sign out" onClick={() => supabase!.auth.signOut()}>
        <LogOut />
      </Button>
    </div>
  );
}

function BackendOffline() {
  return (
    <Alert className="mx-auto mb-6 max-w-3xl">
      <PlugZap />
      <AlertTitle>Voxwell isn't running on this computer</AlertTitle>
      <AlertDescription>
        <p>
          Everything Voxwell does happens on your own computer: this page only shows the controls. Start Voxwell (the
          desktop app, or <code>uv run voxwell</code> in the <code>backend</code> folder) and this page connects by itself.
        </p>
        <p>If your browser asks whether this site may connect to apps on your device, choose Allow.</p>
      </AlertDescription>
    </Alert>
  );
}

function FeatureMenu({ active, onSelect }: { active: string; onSelect: (id: string) => void }) {
  // On phones the sidebar is a slide-over panel; picking a page must also close it.
  const { setOpenMobile } = useSidebar();
  return GROUPS.map((group) => (
    <SidebarGroup key={group}>
      <SidebarGroupLabel>{group}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {FEATURES.filter((f) => f.group === group).map((f) => (
            <SidebarMenuItem key={f.id}>
              <SidebarMenuButton
                isActive={f.id === active}
                tooltip={f.title}
                onClick={() => {
                  onSelect(f.id);
                  setOpenMobile(false);
                }}
              >
                <f.icon />
                <span>{f.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  ));
}

function Shell({ user }: { user?: User }) {
  const [active, setActive] = useState(FEATURES[0].id);
  const [online, setOnline] = useState<boolean | null>(null);
  // Bumped when the backend comes back, so the open page reloads its data.
  const [connection, setConnection] = useState(0);

  useEffect(() => {
    api('/api/health').then(() => setOnline(true), () => setOnline(false));
  }, []);

  useEffect(() => {
    if (online !== false) return;
    const timer = window.setInterval(() => {
      api('/api/health').then(() => {
        setOnline(true);
        setConnection((n) => n + 1);
      }, () => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [online]);

  const feature = FEATURES.find((f) => f.id === active)!;

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center gap-2.5 px-1 py-1.5">
            <LogoMark className="size-8" />
            <span className="text-xl font-bold tracking-tight group-data-[collapsible=icon]:hidden">Voxwell</span>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <FeatureMenu active={active} onSelect={setActive} />
        </SidebarContent>
        <SidebarFooter>
          {user && <Account user={user} />}
          <div className="flex items-center gap-2 px-1 group-data-[collapsible=icon]:flex-col">
            <span
              className={cn('size-2 shrink-0 rounded-full', online === null ? 'bg-muted-foreground' : online ? 'bg-success' : 'bg-destructive')}
              title={online === null ? 'Connecting…' : online ? 'Backend online' : 'Backend offline'}
            />
            <span className="text-muted-foreground flex-1 text-xs group-data-[collapsible=icon]:hidden">
              {online === null ? 'Connecting…' : online ? 'Backend online' : 'Backend offline'}
            </span>
            <ThemeToggle />
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="bg-background/80 sticky top-0 z-10 flex h-12 items-center gap-2 border-b px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1 size-9 md:size-7" />
          <span className="text-muted-foreground text-sm">{feature.group}</span>
          <span className="text-muted-foreground text-sm">/</span>
          <span className="text-sm font-medium">{feature.title}</span>
        </header>
        <main className="flex-1 p-4 sm:p-6 md:p-8">
          {online === false && <BackendOffline />}
          <feature.Page key={`${feature.id}-${connection}`} />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

export default function App() {
  const { session, recovering, endRecovery } = useSession();
  return (
    <TooltipProvider>
      {session === undefined ? null : supabase && (!session || recovering) ? (
        <AuthPage recovering={recovering} onRecovered={endRecovery} />
      ) : (
        <Shell user={session?.user} />
      )}
      <Toaster position="bottom-right" />
    </TooltipProvider>
  );
}
