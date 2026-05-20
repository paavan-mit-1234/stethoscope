import { cloudMode, getAuth } from "./cloud";
import { LoginModal } from "./components/LoginModal";
import { Splash } from "./components/Splash";
import { Workbench } from "./components/Workbench";
import { useStore } from "./store";

export default function App() {
  const splashDone = useStore((s) => s.splashDone);
  // Cloud-mode wall (Cloud Phase 2). Desktop mode is unchanged.
  if (cloudMode && !getAuth()) return <LoginModal />;
  return splashDone ? <Workbench /> : <Splash />;
}
