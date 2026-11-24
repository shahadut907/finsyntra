// Central navigation map for FinSyntra
export const NAV = [
  { 
    key: "home", 
    path: "/", 
    icon: "Home", 
    label: "Home",
    description: "Landing page with quick start options"
  },
  { 
    key: "chat", 
    path: "/chat", 
    icon: "MessageSquare", 
    label: "Chat",
    description: "AI Assistant conversation interface" 
  },
  { 
    key: "history", 
    path: "/history", 
    icon: "History", 
    label: "History",
    description: "Conversation history and exports"
  },
  { 
    key: "search", 
    path: "/search", 
    icon: "Search", 
    label: "Search",
    description: "Search documents and conversations"
  },
  {
    key: "docs",
    path: "/documents",
    icon: "BookOpen",
    label: "Documents",
    description: "Document library and management"
  },
  {
    key: "stats",
    path: "/reports",
    icon: "BarChart3",
    label: "Reports",
    description: "Analytics and insights dashboard"
  }
];

// Route definitions for authentication and access control
export const PROTECTED_ROUTES = ["/chat", "/history", "/documents", "/reports"];
export const ADMIN_ROUTES = ["/admin", "/reports"];

export default NAV;
