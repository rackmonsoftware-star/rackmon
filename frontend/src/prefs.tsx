import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Theme = "dark" | "light";
type Lang = "en" | "es";

const THEME_KEY = "rackmon_theme";
const LANG_KEY = "rackmon_lang";

// --- Translation dictionary ----------------------------------------------- //
const DICT: Record<Lang, Record<string, string>> = {
  en: {
    supportGithub: "Or open an issue on GitHub — that is where the project is worked on.",
    overview: "Overview",
    devices: "Devices",
    alerts: "Alerts",
    rules: "Rules",
    admin: "Admin",
    logout: "Sign out",
    signIn: "Sign in",
    appTagline: "Thermal monitoring for server racks",
    builtBy: "Built by Enrique González Romero",
    email: "Email",
    password: "Password",
    mfaCode: "2FA code (if enabled)",
    devicesTotal: "Devices",
    activeAlerts: "Active alerts",
    avgTemp: "Avg temperature",
    maxTemp: "Peak temperature",
    rackHeatmap: "Rack thermal map",
    hottest: "Hottest devices",
    statusBreakdown: "Fleet status",
    noData: "No data",
    statusOk: "Nominal",
    statusWarning: "Warning",
    statusCritical: "Critical",
    statusNodata: "No data",
    statusMaintenance: "Maintenance",
    licenseExpired: "Your Pro licence has expired. The status page, SLA reports and white-label branding are off; everything else keeps working.",
    licenseExpiresToday: "Your Pro licence expires today.",
    licenseExpiresIn: "Your Pro licence expires in {n} days.",
    licenseRenew: "Renew",
    muteNoRules: "No alert rules are enabled. RackMon is polling and drawing charts, but it cannot notify you about anything.",
    muteNoChannels: "No notification channel is configured. Alerts will be recorded and shown here, but nothing will leave this machine.",
    muteFix: "Fix this",
    nominal: "Nominal",
    warning: "Warning",
    critical: "Critical",
    maintenance: "Maintenance",
    addDevice: "Add device",
    addUser: "Add user",
    manageDevices: "Manage devices",
    update: "Update",
    updateAvailable: "Update available",
    viewUpdate: "View",
    dismiss: "Dismiss",
    updates: "Updates",
    updateChecks: "Check for updates",
    updateChecksHint: "When on, RackMon periodically fetches a small version file from the vendor to tell you when a new release is out. No usage data is sent.",
    updateChannel: "Channel",
    manifestUrl: "Manifest URL (optional)",
    name: "Name",
    ip: "IP address",
    vendor: "Vendor",
    rack: "Rack",
    position: "Position (U)",
    tags: "Tags",
    community: "SNMP community",
    version: "SNMP version",
    search: "Search devices…",
    temperature: "Temperature",
    status: "Status",
    lastSeen: "Last seen",
    live: "Live",
    history: "History",
    range: "Range",
    export: "Export CSV",
    enterMaintenance: "Enter maintenance",
    exitMaintenance: "Exit maintenance",
    delete: "Delete",
    edit: "Edit",
    profile: "Profile",
    changePassword: "Change password",
    currentPassword: "Current password",
    newPassword: "New password",
    confirm: "Confirm password",
    twoFactor: "Two-factor authentication",
    enable2fa: "Enable 2FA",
    disable2fa: "Disable 2FA",
    verificationCode: "Verification code",
    snooze: "Snooze",
    snoozed: "Snoozed",
    testNotification: "Send test",
    selectAll: "Select all",
    deleteSelected: "Delete selected",
    resetPassword: "Reset password",
    disableUser: "Disable",
    enableUser: "Enable",
    rename: "Rename",
    customRange: "Custom",
    allStatuses: "All statuses",
    allRacks: "All racks",
    addMetric: "Add metric",
    cancel: "Cancel",
    save: "Save",
    create: "Create",
    acknowledge: "Acknowledge",
    resolve: "Resolve",
    comment: "Comment",
    severity: "Severity",
    metric: "Metric",
    threshold: "Threshold",
    scope: "Scope",
    active: "Active",
    firing: "Firing",
    acked: "Acknowledged",
    resolved: "Resolved",
    noAlerts: "No active alerts. All systems nominal.",
    noDevices: "No devices yet. Add one to begin monitoring.",
    connecting: "Connecting…",
    connected: "Live",
    disconnected: "Reconnecting…",
    users: "Users",
    auditLog: "Audit log",
    role: "Role",
    action: "Action",
    time: "Time",
    loading: "Loading…",
    signingIn: "Signing you in…",
    ssoNoTokens: "The identity provider did not return a session. Try signing in again.",
    backToLogin: "Back to sign in",
    reports: "Reports",
    discover: "Discover",
    kiosk: "Kiosk",
    fromLabel: "From",
    toLabel: "To",
    downloadPdf: "Download PDF",
    scan: "Scan",
    target: "Target (CIDR / range / IP)",
    importSelected: "Import selected",
    alreadyAdded: "Already added",
    availability: "Availability",
    overWarn: "% over warn",
    overCrit: "% over crit",
    lastDays: "Last 7 days",
    summary: "Summary",
    notes: "Notes",
    addNote: "Add note",
    signInSSO: "Sign in with SSO",
    compare: "Compare",
    settings: "Settings",
    enabled: "Enabled",
    recipients: "Recipients (comma-separated)",
    afterMinutes: "Escalate after (minutes)",
    saved: "Saved",
    useLdap: "Sign in with LDAP",
    incidents: "Correlated incidents",
    relatedAlerts: "related alerts",
    template: "Template",
    none: "None",
    anomalies: "Anomalies",
    anomaliesDetected: "anomalies detected",
    noAnomalies: "No anomalies detected",
    apiKeys: "API keys",
    backup: "Backup",
    createKey: "Create key",
    revoke: "Revoke",
    copyKey: "Copy this key now — it is shown only once",
    downloadBackup: "Download backup",
    restoreBackup: "Restore from file",
    lastUsed: "Last used",
    condition: "Condition",
    selectedCount: "selected",
    copy: "Copy",
    prefix: "Prefix",
    targetCol: "Target",
    escalation: "escalation",
    weeklyReportDesc: "weekly PDF report by email",
    selectDevicesToCompare: "Select devices to compare",
    backupDesc:
      "Export your configuration (devices, rules, settings) to a file, or restore it on this or another instance.",
    mfaSetupHint:
      "Add this secret to your authenticator app (or scan the URL), then enter the 6-digit code to confirm.",
    mfaActive: "Two-factor authentication is active on your account.",
    passwordUpdated: "Password updated",
    mfaEnabledMsg: "Two-factor authentication enabled",
    mfaDisabledMsg: "Two-factor authentication disabled",
    passwordsNoMatch: "Passwords do not match",
    statusPage: "Status page",
    statusPageDesc: "Public, read-only health board",
    pageTitle: "Page title",
    showTemperatures: "Show temperatures",
    openPublicPage: "Open public page",
    slaReport: "SLA report",
    slaTarget: "SLA target %",
    downtime: "Downtime (min)",
    incidentsCount: "Incidents",
    mttr: "MTTR (min)",
    overallAvailability: "Overall availability",
    branding: "Branding (white-label)",
    productName: "Product name",
    accentColor: "Accent color",
    logoUrl: "Logo URL (optional)",
    support: "Feedback",
    supportTitle: "Bugs, ideas and questions",
    supportHint: "Every message goes straight to the maker. You'll get a reply by email.",
    supportKind: "What is it?",
    supportKindBug: "Bug",
    supportKindIdea: "Idea",
    supportKindQuestion: "Question",
    supportPlaceholderBug: "What happened, what you expected, and how to reproduce it.",
    supportPlaceholderIdea: "What would make RackMon more useful for you?",
    supportPlaceholderQuestion: "Ask anything.",
    supportMessage: "Your message",
    supportEmail: "Your email (for the reply)",
    send: "Send",
    supportSent: "Message sent — we'll get back to you by email. Thanks!",
    supportError: "Couldn't send. Please try again in a moment.",
    supportDisabled: "This instance has no support desk configured. Ask your administrator, or report it at rackmon.app/feedback.html.",
    demoEnter: "Explore the live demo →",
  },
  es: {
    supportGithub: "O abre una incidencia en GitHub — es donde se trabaja el proyecto.",
    overview: "Resumen",
    devices: "Dispositivos",
    alerts: "Alertas",
    rules: "Reglas",
    admin: "Administración",
    logout: "Cerrar sesión",
    signIn: "Iniciar sesión",
    appTagline: "Monitorización térmica de racks de servidores",
    builtBy: "Hecho por Enrique González Romero",
    email: "Correo",
    password: "Contraseña",
    mfaCode: "Código 2FA (si está activo)",
    devicesTotal: "Dispositivos",
    activeAlerts: "Alertas activas",
    avgTemp: "Temperatura media",
    maxTemp: "Temperatura máxima",
    rackHeatmap: "Mapa térmico del rack",
    hottest: "Dispositivos más calientes",
    statusBreakdown: "Estado del parque",
    noData: "Sin datos",
    statusOk: "Normal",
    statusWarning: "Aviso",
    statusCritical: "Crítico",
    statusNodata: "Sin datos",
    statusMaintenance: "Mantenimiento",
    licenseExpired: "Tu licencia Pro ha caducado. La página de estado, los informes de SLA y la marca blanca están apagados; lo demás sigue funcionando.",
    licenseExpiresToday: "Tu licencia Pro caduca hoy.",
    licenseExpiresIn: "A tu licencia Pro le quedan {n} días.",
    licenseRenew: "Renovar",
    muteNoRules: "No hay ninguna regla de alerta activa. RackMon está sondeando y pintando gráficas, pero no puede avisarte de nada.",
    muteNoChannels: "No hay ningún canal de notificación configurado. Las alertas se registrarán y se verán aquí, pero no saldrá nada de esta máquina.",
    muteFix: "Arreglarlo",
    nominal: "Normal",
    warning: "Advertencia",
    critical: "Crítico",
    maintenance: "Mantenimiento",
    addDevice: "Añadir dispositivo",
    addUser: "Añadir usuario",
    manageDevices: "Gestionar dispositivos",
    update: "Actualización",
    updateAvailable: "Actualización disponible",
    viewUpdate: "Ver",
    dismiss: "Descartar",
    updates: "Actualizaciones",
    updateChecks: "Buscar actualizaciones",
    updateChecksHint: "Si se activa, RackMon consulta periódicamente un pequeño fichero de versión del proveedor para avisarte de nuevas versiones. No se envía ningún dato de uso.",
    updateChannel: "Canal",
    manifestUrl: "URL del manifiesto (opcional)",
    name: "Nombre",
    ip: "Dirección IP",
    vendor: "Fabricante",
    rack: "Rack",
    position: "Posición (U)",
    tags: "Etiquetas",
    community: "Comunidad SNMP",
    version: "Versión SNMP",
    search: "Buscar dispositivos…",
    temperature: "Temperatura",
    status: "Estado",
    lastSeen: "Visto por última vez",
    live: "En vivo",
    history: "Histórico",
    range: "Rango",
    export: "Exportar CSV",
    enterMaintenance: "Entrar en mantenimiento",
    exitMaintenance: "Salir de mantenimiento",
    delete: "Eliminar",
    edit: "Editar",
    profile: "Perfil",
    changePassword: "Cambiar contraseña",
    currentPassword: "Contraseña actual",
    newPassword: "Nueva contraseña",
    confirm: "Confirmar contraseña",
    twoFactor: "Autenticación de dos factores",
    enable2fa: "Activar 2FA",
    disable2fa: "Desactivar 2FA",
    verificationCode: "Código de verificación",
    snooze: "Posponer",
    snoozed: "Pospuesta",
    testNotification: "Enviar prueba",
    selectAll: "Seleccionar todo",
    deleteSelected: "Borrar seleccionados",
    resetPassword: "Restablecer contraseña",
    disableUser: "Desactivar",
    enableUser: "Activar",
    rename: "Renombrar",
    customRange: "Personalizado",
    allStatuses: "Todos los estados",
    allRacks: "Todos los racks",
    addMetric: "Añadir métrica",
    cancel: "Cancelar",
    save: "Guardar",
    create: "Crear",
    acknowledge: "Reconocer",
    resolve: "Resolver",
    comment: "Comentario",
    severity: "Severidad",
    metric: "Métrica",
    threshold: "Umbral",
    scope: "Ámbito",
    active: "Activas",
    firing: "Disparada",
    acked: "Reconocida",
    resolved: "Resuelta",
    noAlerts: "No hay alertas activas. Todos los sistemas normales.",
    noDevices: "Aún no hay dispositivos. Añade uno para empezar a monitorizar.",
    connecting: "Conectando…",
    connected: "En vivo",
    disconnected: "Reconectando…",
    users: "Usuarios",
    auditLog: "Registro de auditoría",
    role: "Rol",
    action: "Acción",
    time: "Hora",
    loading: "Cargando…",
    signingIn: "Entrando…",
    ssoNoTokens: "El proveedor de identidad no ha devuelto ninguna sesión. Vuelve a intentarlo.",
    backToLogin: "Volver al inicio de sesión",
    reports: "Informes",
    discover: "Descubrir",
    kiosk: "Kiosco",
    fromLabel: "Desde",
    toLabel: "Hasta",
    downloadPdf: "Descargar PDF",
    scan: "Escanear",
    target: "Objetivo (CIDR / rango / IP)",
    importSelected: "Importar seleccionados",
    alreadyAdded: "Ya añadido",
    availability: "Disponibilidad",
    overWarn: "% sobre aviso",
    overCrit: "% sobre crítico",
    lastDays: "Últimos 7 días",
    summary: "Resumen",
    notes: "Notas",
    addNote: "Añadir nota",
    signInSSO: "Entrar con SSO",
    compare: "Comparar",
    settings: "Ajustes",
    enabled: "Activado",
    recipients: "Destinatarios (separados por comas)",
    afterMinutes: "Escalar tras (minutos)",
    saved: "Guardado",
    useLdap: "Entrar con LDAP",
    incidents: "Incidentes correlacionados",
    relatedAlerts: "alertas relacionadas",
    template: "Plantilla",
    none: "Ninguna",
    anomalies: "Anomalías",
    anomaliesDetected: "anomalías detectadas",
    noAnomalies: "Sin anomalías detectadas",
    apiKeys: "Claves de API",
    backup: "Copia de seguridad",
    createKey: "Crear clave",
    revoke: "Revocar",
    copyKey: "Copia esta clave ahora: solo se muestra una vez",
    downloadBackup: "Descargar copia",
    restoreBackup: "Restaurar desde archivo",
    lastUsed: "Último uso",
    condition: "Condición",
    selectedCount: "seleccionados",
    copy: "Copiar",
    prefix: "Prefijo",
    targetCol: "Objetivo",
    escalation: "escalado",
    weeklyReportDesc: "informe PDF semanal por correo",
    selectDevicesToCompare: "Selecciona dispositivos para comparar",
    backupDesc:
      "Exporta tu configuración (dispositivos, reglas, ajustes) a un archivo, o restáurala en esta u otra instancia.",
    mfaSetupHint:
      "Añade este secreto a tu app de autenticación (o escanea la URL) e introduce el código de 6 dígitos para confirmar.",
    mfaActive: "La autenticación de dos factores está activa en tu cuenta.",
    passwordUpdated: "Contraseña actualizada",
    mfaEnabledMsg: "Autenticación de dos factores activada",
    mfaDisabledMsg: "Autenticación de dos factores desactivada",
    passwordsNoMatch: "Las contraseñas no coinciden",
    statusPage: "Página de estado",
    statusPageDesc: "Panel de salud público de solo lectura",
    pageTitle: "Título de la página",
    showTemperatures: "Mostrar temperaturas",
    openPublicPage: "Abrir página pública",
    slaReport: "Informe SLA",
    slaTarget: "Objetivo SLA %",
    downtime: "Caída (min)",
    incidentsCount: "Incidencias",
    mttr: "MTTR (min)",
    overallAvailability: "Disponibilidad global",
    branding: "Marca (marca blanca)",
    productName: "Nombre del producto",
    accentColor: "Color de acento",
    logoUrl: "URL del logo (opcional)",
    support: "Opinar",
    supportTitle: "Fallos, ideas y preguntas",
    supportHint: "Cada mensaje llega directo al creador. Te responderá por email.",
    supportKind: "¿Qué es?",
    supportKindBug: "Fallo",
    supportKindIdea: "Idea",
    supportKindQuestion: "Pregunta",
    supportPlaceholderBug: "Qué ha pasado, qué esperabas y cómo reproducirlo.",
    supportPlaceholderIdea: "¿Qué haría RackMon más útil para ti?",
    supportPlaceholderQuestion: "Pregunta lo que quieras.",
    supportMessage: "Tu mensaje",
    supportEmail: "Tu email (para la respuesta)",
    send: "Enviar",
    supportSent: "Mensaje enviado — te responderemos por email. ¡Gracias!",
    supportError: "No se pudo enviar. Inténtalo de nuevo en un momento.",
    supportDisabled: "Esta instancia no tiene canal de soporte configurado. Pregunta a tu administrador o escríbenos en rackmon.app/feedback.html.",
    demoEnter: "Entrar a la demo →",
  },
};

interface PrefsCtx {
  theme: Theme;
  lang: Lang;
  toggleTheme: () => void;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const Ctx = createContext<PrefsCtx | null>(null);

/** En ventana privada o con las cookies bloqueadas, leer localStorage lanza. Sin
    esto la aplicación entera se quedaba en blanco en vez de arrancar con los
    valores del sistema. */
function guardado(clave: string): string | null {
  try {
    return localStorage.getItem(clave);
  } catch {
    return null;
  }
}

function initialTheme(): Theme {
  const saved = guardado(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  const prefersLight =
    window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  return prefersLight ? "light" : "dark";
}

function initialLang(): Lang {
  const saved = guardado(LANG_KEY);
  if (saved === "en" || saved === "es") return saved;
  return navigator.language.toLowerCase().startsWith("es") ? "es" : "en";
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [lang, setLangState] = useState<Lang>(initialLang);

  // OJO: aquí NO se guarda nada. Antes este efecto escribía en localStorage en
  // cada montaje, así que la primera visita de la vida dejaba grabado lo que el
  // sistema dijera en ese momento y `prefers-color-scheme` no se volvía a mirar
  // jamás. Quien entrara una vez con el sistema en claro y luego se pasara a
  // oscuro se quedaba en claro para siempre, sin haber elegido nada. Guardar es
  // decisión del usuario, y eso pasa en toggleTheme/setLang.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("dark", "light");
    root.classList.add(theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  // Mientras el usuario no haya elegido, se sigue al sistema en vivo: si cambia
  // el tema del sistema a media tarde, la aplicación cambia con él.
  useEffect(() => {
    if (!window.matchMedia) return;
    let guardado: string | null = null;
    try { guardado = localStorage.getItem(THEME_KEY); } catch { /* modo privado */ }
    if (guardado === "light" || guardado === "dark") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const alCambiar = (e: MediaQueryListEvent) => {
      // Se vuelve a mirar AQUÍ, no solo al montar. El efecto se instala una vez
      // y no se entera de que el usuario haya pulsado el interruptor después:
      // una pantalla de NOC puesta en claro a propósito para el turno de día se
      // volvía oscura sola al anochecer, cuando el sistema operativo cambiaba de
      // apariencia, y volvía al claro en el siguiente refresco. Si ya ha
      // elegido, su elección manda.
      let elegido: string | null = null;
      try { elegido = localStorage.getItem(THEME_KEY); } catch { /* modo privado */ }
      if (elegido === "light" || elegido === "dark") return;
      setTheme(e.matches ? "dark" : "light");
    };
    mq.addEventListener?.("change", alCambiar);
    return () => mq.removeEventListener?.("change", alCambiar);
  }, []);

  // Guardar es un acto del usuario, no un efecto secundario de pintar. Desde
  // aquí sí se graba: ha elegido, y a partir de ahora manda su elección.
  const toggleTheme = useCallback(
    () =>
      setTheme((t) => {
        const nuevo = t === "dark" ? "light" : "dark";
        try { localStorage.setItem(THEME_KEY, nuevo); } catch { /* modo privado */ }
        return nuevo;
      }),
    [],
  );
  const setLang = useCallback((l: Lang) => {
    try { localStorage.setItem(LANG_KEY, l); } catch { /* modo privado */ }
    setLangState(l);
  }, []);
  const t = useCallback(
    (key: string) => DICT[lang][key] ?? DICT.en[key] ?? key,
    [lang],
  );

  const value = useMemo(
    () => ({ theme, lang, toggleTheme, setLang, t }),
    [theme, lang, toggleTheme, setLang, t],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePrefs(): PrefsCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePrefs must be used within PrefsProvider");
  return ctx;
}
