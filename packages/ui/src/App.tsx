import { Splash } from "./components/Splash";
import { Workbench } from "./components/Workbench";
import { useStore } from "./store";

export default function App() {
  const splashDone = useStore((s) => s.splashDone);
  return splashDone ? <Workbench /> : <Splash />;
}
