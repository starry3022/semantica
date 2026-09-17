import { createContext } from "react";

// Portals are outside the retained workspace's DOM layer but share its activity.
export const WorkspaceActivityContext = createContext(true);
