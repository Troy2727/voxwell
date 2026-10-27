import { useEffect, useState } from 'react';
import type { User } from '@supabase/supabase-js';
import { LogOut, Moon, Sun } from 'lucide-react';
import { api } from './api';
import { AuthPage } from './auth/AuthPage';
import { FEATURES } from './features';
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

function Shell({ user }: { user?: User }) {
  const [active, setActive] = useState(FEATURES[0].id);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    api('/api/health').then(() => setOnline(true), () => setOnline(false));
  }, []);

  const feature = FEATURES.find((f) => f.id === active)!;

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <div className="flex items-center gap-2 px-1 py-1.5">
            <img src="favicon.svg" alt="" className="size-7 shrink-0" />
            <span className="text-lg font-bold tracking-tight group-data-[collapsible=icon]:hidden">Voxwell</span>
          </div>
        </SidebarHeader>
        <SidebarContent>
          {GROUPS.map((group) => (
            <SidebarGroup key={group}>
              <SidebarGroupLabel>{group}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {FEATURES.filter((f) => f.group === group).map((f) => (
                    <SidebarMenuItem key={f.id}>
                      <SidebarMenuButton isActive={f.id === active} tooltip={f.title} onClick={() => setActive(f.id)}>
                        <f.icon />
                        <span>{f.title}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
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
          <SidebarTrigger className="-ml-1" />
          <span className="text-muted-foreground text-sm">{feature.group}</span>
          <span className="text-muted-foreground text-sm">/</span>
          <span className="text-sm font-medium">{feature.title}</span>
        </header>
        <main className="flex-1 p-6 md:p-8">
          <feature.Page key={feature.id} />
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
