import {
  LayoutDashboard, Users, CreditCard, Megaphone, Share2, Gift,
  ScrollText, Settings, type LucideIcon,
} from "lucide-react";

export interface NavItem { to: string; label: string; icon: LucideIcon; }
export interface NavSection { label: string; items: NavItem[]; }

export const sections: NavSection[] = [
  {
    label: "Главное",
    items: [
      { to: "", label: "Главная", icon: LayoutDashboard },
      { to: "users", label: "Пользователи", icon: Users },
      { to: "payments", label: "Платежи", icon: CreditCard },
    ],
  },
  {
    label: "Маркетинг",
    items: [
      { to: "broadcasts", label: "Рассылки", icon: Megaphone },
      { to: "referrals", label: "Рефералы", icon: Share2 },
      { to: "gifts", label: "Гифты", icon: Gift },
    ],
  },
  {
    label: "Система",
    items: [
      { to: "audit", label: "Аудит", icon: ScrollText },
      { to: "settings", label: "Настройки", icon: Settings },
    ],
  },
];

// Key items shown in the mobile bottom bar.
export const mobileItems: NavItem[] = [
  sections[0].items[0],
  sections[0].items[1],
  sections[0].items[2],
  sections[1].items[0],
  sections[2].items[1],
];
