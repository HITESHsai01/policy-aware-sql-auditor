"""
Styling and Theme Definition for Policy-Aware SQL Auditor Console.

Implements a crisp, low-glare dark engineering aesthetic.
"""

import streamlit as st


def inject_custom_css() -> None:
    """Injects high-density, professional developer console CSS."""
    st.markdown(
        """
        <style>
        /* Base Viewport & Reset */
        .main .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2.0rem;
            max-width: 1440px;
        }

        /* Top System Bar */
        .sys-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
            background: #0f141f;
            border: 1px solid #1e2638;
            border-radius: 6px;
            padding: 10px 16px;
            margin-bottom: 16px;
            font-family: ui-monospace, "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
        }
        .sys-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 13px;
            font-weight: 700;
            color: #f1f5f9;
            letter-spacing: 0.04em;
            white-space: nowrap;
        }
        .sys-tag {
            font-size: 10px;
            padding: 2px 7px;
            border-radius: 3px;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        .tag-airgap {
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.35);
            color: #34d399;
        }
        .tag-muted {
            background: rgba(148, 163, 184, 0.1);
            border: 1px solid rgba(148, 163, 184, 0.2);
            color: #94a3b8;
        }
        .sys-telemetry {
            display: flex;
            align-items: center;
            gap: 18px;
            font-size: 11px;
            color: #94a3b8;
            white-space: nowrap;
        }
        .sys-telemetry span {
            color: #cbd5e1;
            font-weight: 600;
        }

        /* Pipeline Flow Stepper */
        .pipeline-stepper {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            background: #0b0f17;
            border: 1px solid #1c2333;
            border-radius: 6px;
            padding: 8px 12px;
            margin-bottom: 14px;
            font-family: ui-monospace, "SF Mono", monospace;
            font-size: 11px;
        }
        .step-node {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 10px;
            background: #111724;
            border: 1px solid #1e273a;
            border-radius: 4px;
        }
        .step-label {
            color: #94a3b8;
            font-weight: 500;
        }
        .step-val {
            font-weight: 700;
            font-size: 10.5px;
            padding: 1px 6px;
            border-radius: 3px;
        }
        .val-pass {
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.4);
            color: #34d399;
        }
        .val-repair {
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid rgba(245, 158, 11, 0.4);
            color: #fbbf24;
        }
        .val-fail {
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid rgba(244, 63, 94, 0.4);
            color: #f43f5e;
        }
        .val-skip {
            background: rgba(100, 116, 139, 0.15);
            border: 1px solid rgba(100, 116, 139, 0.3);
            color: #94a3b8;
        }

        /* High-Density KPI Metric Strip */
        .metric-strip {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-bottom: 16px;
        }
        .metric-box {
            background: #0d121c;
            border: 1px solid #1c2436;
            border-radius: 5px;
            padding: 10px 14px;
        }
        .metric-box .label {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #64748b;
            margin-bottom: 4px;
        }
        .metric-box .val {
            font-family: ui-monospace, "SF Mono", monospace;
            font-size: 16px;
            font-weight: 700;
            color: #f8fafc;
        }

        /* Decision Status Banners */
        .status-verdict {
            border-radius: 5px;
            padding: 12px 16px;
            margin-bottom: 16px;
            font-size: 13px;
            line-height: 1.5;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .status-approved {
            background: rgba(16, 185, 129, 0.08);
            border: 1px solid rgba(16, 185, 129, 0.35);
            color: #a7f3d0;
        }
        .status-repaired {
            background: rgba(245, 158, 11, 0.08);
            border: 1px solid rgba(245, 158, 11, 0.35);
            color: #fde68a;
        }
        .status-rejected {
            background: rgba(244, 63, 94, 0.08);
            border: 1px solid rgba(244, 63, 94, 0.35);
            color: #fecdd3;
        }
        .status-ambiguous {
            background: rgba(56, 189, 248, 0.08);
            border: 1px solid rgba(56, 189, 248, 0.35);
            color: #bae6fd;
        }

        /* Section Containers */
        .panel-card {
            background: #0f141f;
            border: 1px solid #1e2638;
            border-radius: 6px;
            padding: 14px 16px;
            margin-bottom: 14px;
        }
        .panel-title {
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #94a3b8;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #1a2233;
        }

        /* Diff Styling */
        .diff-added {
            background: rgba(16, 185, 129, 0.12);
            color: #34d399;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: ui-monospace, "SF Mono", monospace;
            font-size: 12px;
        }
        .diff-removed {
            background: rgba(244, 63, 94, 0.12);
            color: #f43f5e;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: ui-monospace, "SF Mono", monospace;
            font-size: 12px;
        }

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background: #090d14;
            border-right: 1px solid #1a2233;
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 1.2rem;
        }

        /* Clean Tab Navigation */
        button[data-baseweb="tab"] {
            font-family: ui-monospace, "SF Mono", monospace;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

