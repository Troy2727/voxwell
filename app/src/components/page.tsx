import type { ReactNode } from 'react';
import { AlertCircle, type LucideIcon } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

/** The top of every feature page: title, one-line description, optional actions on the right. */
export function Page({ title, description, actions, children }: { title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <header className="flex items-start gap-4">
        <div className="flex flex-1 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="text-muted-foreground text-sm">{description}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

/** A titled card holding one task on a page. */
export function Section({ title, description, action, className, children }: { title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string; children?: ReactNode }) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      {children && <CardContent className="flex flex-col gap-4">{children}</CardContent>}
    </Card>
  );
}

/** A labelled form control with an optional hint underneath. */
export function Field({ label, hint, htmlFor, className, children }: { label: ReactNode; hint?: ReactNode; htmlFor?: string; className?: string; children: ReactNode }) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}

export function ErrorAlert({ message }: { message: string }) {
  if (!message) return null;
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertDescription className="break-words">{message}</AlertDescription>
    </Alert>
  );
}

/** Nothing to show yet: an icon, a short title and what to do next. */
export function EmptyState({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center">
      <div className="bg-muted text-muted-foreground mb-1 flex size-10 items-center justify-center rounded-full">
        <Icon className="size-5" />
      </div>
      <p className="font-medium">{title}</p>
      {children && <p className="text-muted-foreground max-w-sm text-sm">{children}</p>}
    </div>
  );
}

export function Muted({ className, children }: { className?: string; children: ReactNode }) {
  return <p className={cn('text-muted-foreground text-sm', className)}>{children}</p>;
}

export const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
