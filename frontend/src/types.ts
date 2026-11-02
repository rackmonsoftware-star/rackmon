export type Role = "admin" | "operator" | "viewer";

export interface User {
  id: number;
  email: string;
  role: Role;
  is_active: boolean;
  mfa_enabled: boolean;
  last_login_at: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface MetricCatalog {
  id: number;
  name: string;
  unit: string;
  oid: string;
  // Factor que convierte el valor crudo del SNMP en la unidad de `unit`
  // (0.1 para los OID que devuelven décimas, como iDRAC o APC). El backend ya
  // lo aplica antes de guardar, así que los valores que llegan aquí van en la
  // unidad real: esto es informativo.
  scale: number;
  enabled: boolean;
  poll_interval_s: number;
  warn_threshold: number | null;
  crit_threshold: number | null;
}

export interface Device {
  id: number;
  name: string;
  hostname: string | null;
  ip: string;
  snmp_version: string;
  snmp_port: number;
  vendor: string | null;
  model: string | null;
  rack: string | null;
  position_u: number | null;
  size_u: number;
  tags: string[];
  enabled: boolean;
  has_community: boolean;
  in_maintenance: boolean;
  created_at: string;
  metrics: MetricCatalog[];
}

export type DeviceStatusKind =
  | "ok"
  | "warning"
  | "critical"
  | "nodata"
  | "maintenance";

export interface DeviceStatus {
  device: Device;
  status: DeviceStatusKind;
  temperature: number | null;
  /** De que metrica salio `temperature`. La interfaz la necesita para elegir
      la escala de color: 32 grados de entrada es critico, de CPU es reposo. */
  temperature_metric?: string | null;
  last_seen: string | null;
  firing_alerts: number;
}

export interface Overview {
  devices_total: number;
  status_counts: Record<DeviceStatusKind, number>;
  firing_alerts: number;
  hottest: DeviceStatus[];
  avg_temperature: number | null;
  max_temperature: number | null;
  /** Reglas de alerta encendidas. 0 = el motor no puede disparar nada. */
  alert_rules_active?: number;
  /** Canales de notificacion reales, sin contar la consola. 0 = nada sale de aqui. */
  notification_channels?: number;
  /** La demo publica: ahi el aviso de instalacion muda no informa de nada. */
  demo_mode?: boolean;
}

export interface Sample {
  t: string;
  v: number;
}

export interface MetricSeries {
  device_id: number;
  metric: string;
  unit: string;
  aggregation: string;
  samples: Sample[];
}

export type Severity = "info" | "warning" | "critical";
export type AlertState = "firing" | "acked" | "resolved";

export interface Alert {
  id: number;
  rule_id: number | null;
  device_id: number;
  metric: string;
  severity: Severity;
  state: AlertState;
  value: number | null;
  message: string;
  started_at: string;
  ended_at: string | null;
  acked_by: number | null;
  acked_at: string | null;
  ack_comment: string | null;
  resolved_by: number | null;
  resolved_at: string | null;
  resolve_comment: string | null;
  snoozed_until?: string | null;
}

export interface AlertRule {
  id: number;
  name: string;
  description: string | null;
  scope_type: "global" | "device" | "tag";
  scope_ref: string | null;
  metric: string;
  operator: ">" | "<" | ">=" | "<=" | "==" | "!=";
  threshold: number;
  for_seconds: number;
  severity: Severity;
  throttle_seconds: number;
  enabled: boolean;
}

export interface AuditEntry {
  id: number;
  actor_id: number | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  ip: string | null;
  created_at: string;
}
