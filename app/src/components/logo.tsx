import { cn } from '@/lib/utils';

/**
 * The Voxwell V. Dark mode shows the bare mark, because the app icon's navy tile blends into dark
 * surfaces and leaves a tiny V; light mode shows the tiled icon, which stands out on cream.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <>
      <img src="favicon.svg" alt="" className={cn('shrink-0 dark:hidden', className)} />
      <img src="mark.svg" alt="" className={cn('hidden shrink-0 dark:block', className)} />
    </>
  );
}
