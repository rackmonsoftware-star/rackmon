{{- define "rackmon.name" -}}rackmon{{- end -}}
{{- define "rackmon.fullname" -}}{{ .Release.Name }}-rackmon{{- end -}}
{{- define "rackmon.labels" -}}
app.kubernetes.io/name: {{ include "rackmon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: rackmon-{{ .Chart.Version }}
{{- end -}}
{{- define "rackmon.secretName" -}}
{{- if .Values.secrets.existingSecret }}{{ .Values.secrets.existingSecret }}{{- else }}{{ include "rackmon.fullname" . }}-secrets{{- end }}
{{- end -}}
{{- define "rackmon.databaseUrl" -}}
{{- if .Values.postgres.enabled -}}
postgresql+psycopg2://rackmon:$(DB_PASSWORD)@{{ include "rackmon.fullname" . }}-postgres:5432/rackmon
{{- else -}}
{{ .Values.postgres.externalDatabaseUrl }}
{{- end -}}
{{- end -}}
