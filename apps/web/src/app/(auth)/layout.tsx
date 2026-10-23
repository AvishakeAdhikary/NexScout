import { DesktopDragStrip } from "@/components/desktop-drag-strip";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <DesktopDragStrip />
      {children}
    </>
  );
}
