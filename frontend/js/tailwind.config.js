/* PricePeek design tokens (shared by every screen).
 *
 * Source: Google Stitch export -> objective_comparison_engine/DESIGN.md
 * The 18 design-system screens all ship these exact values.
 *
 * borderRadius note: the Stitch homepage overrode 2xl to 1.25rem while the other
 * 17 screens used Tailwind's default 1rem. DESIGN.md specifies
 * "rounded-2xl to rounded-3xl = 1rem to 1.5rem", so 1rem is canonical here.
 */
window.tailwind = window.tailwind || {};
const semanticColor = (name) => `rgb(var(--color-${name}) / <alpha-value>)`;
tailwind.config = {
  darkMode: "class",
  theme: {
    extend: {
      "colors": {
        "on-tertiary": semanticColor("on-tertiary"),
        "on-primary-fixed": semanticColor("on-primary-fixed"),
        "on-background": semanticColor("on-background"),
        "outline-variant": semanticColor("outline-variant"),
        "secondary": semanticColor("secondary"),
        "on-tertiary-container": semanticColor("on-tertiary-container"),
        "outline": semanticColor("outline"),
        "surface-container": semanticColor("surface-container"),
        "surface-dim": semanticColor("surface-dim"),
        "inverse-surface": semanticColor("inverse-surface"),
        "surface": semanticColor("surface"),
        "secondary-fixed-dim": semanticColor("secondary-fixed-dim"),
        "on-tertiary-fixed": semanticColor("on-tertiary-fixed"),
        "primary": semanticColor("primary"),
        "tertiary": semanticColor("tertiary"),
        "on-secondary-fixed-variant": semanticColor("on-secondary-fixed-variant"),
        "background": semanticColor("background"),
        "surface-container-lowest": semanticColor("surface-container-lowest"),
        "secondary-container": semanticColor("secondary-container"),
        "on-secondary-container": semanticColor("on-secondary-container"),
        "surface-container-highest": semanticColor("surface-container-highest"),
        "on-secondary-fixed": semanticColor("on-secondary-fixed"),
        "primary-fixed-dim": semanticColor("primary-fixed-dim"),
        "on-surface-variant": semanticColor("on-surface-variant"),
        "tertiary-fixed-dim": semanticColor("tertiary-fixed-dim"),
        "surface-container-low": semanticColor("surface-container-low"),
        "on-tertiary-fixed-variant": semanticColor("on-tertiary-fixed-variant"),
        "on-surface": semanticColor("on-surface"),
        "inverse-primary": semanticColor("inverse-primary"),
        "surface-container-high": semanticColor("surface-container-high"),
        "on-primary-container": semanticColor("on-primary-container"),
        "on-error": semanticColor("on-error"),
        "surface-tint": semanticColor("surface-tint"),
        "on-error-container": semanticColor("on-error-container"),
        "error": semanticColor("error"),
        "inverse-on-surface": semanticColor("inverse-on-surface"),
        "error-container": semanticColor("error-container"),
        "on-primary": semanticColor("on-primary"),
        "on-secondary": semanticColor("on-secondary"),
        "primary-fixed": semanticColor("primary-fixed"),
        "on-primary-fixed-variant": semanticColor("on-primary-fixed-variant"),
        "tertiary-fixed": semanticColor("tertiary-fixed"),
        "secondary-fixed": semanticColor("secondary-fixed"),
        "tertiary-container": semanticColor("tertiary-container"),
        "primary-container": semanticColor("primary-container"),
        "surface-variant": semanticColor("surface-variant"),
        "surface-bright": semanticColor("surface-bright")
      },
      "borderRadius": {
        "DEFAULT": "0.25rem",
        "lg": "0.5rem",
        "xl": "0.75rem",
        "2xl": "1rem",
        "3xl": "1.5rem",
        "full": "9999px"
      },
      "spacing": {
        "space-xl": "2.5rem",
        "margin": "1rem",
        "space-sm": "0.5rem",
        "space-lg": "1.5rem",
        "space-xs": "0.25rem",
        "margin-tablet": "2rem",
        "gutter": "1.25rem",
        "gutter-desktop": "1.5rem",
        "margin-desktop": "3rem",
        "space-md": "1rem"
      },
      "fontFamily": {
        "headline-lg-mobile": ["Plus Jakarta Sans"],
        "label-badge": ["Space Grotesk"],
        "headline-md": ["Plus Jakarta Sans"],
        "display-mobile": ["Plus Jakarta Sans"],
        "price-hero": ["Space Grotesk"],
        "headline-lg": ["Plus Jakarta Sans"],
        "body-sm": ["Plus Jakarta Sans"],
        "display": ["Plus Jakarta Sans"],
        "body-md": ["Plus Jakarta Sans"],
        "price-row": ["Space Grotesk"],
        "body-lg": ["Plus Jakarta Sans"]
      },
      "fontSize": {
        "headline-lg-mobile": ["24px", { "lineHeight": "30px", "letterSpacing": "-0.01em", "fontWeight": "700" }],
        "label-badge": ["11px", { "lineHeight": "14px", "letterSpacing": "0.04em", "fontWeight": "700" }],
        "headline-md": ["22px", { "lineHeight": "28px", "letterSpacing": "-0.01em", "fontWeight": "700" }],
        "display-mobile": ["30px", { "lineHeight": "36px", "letterSpacing": "-0.02em", "fontWeight": "800" }],
        "price-hero": ["32px", { "lineHeight": "36px", "letterSpacing": "-0.03em", "fontWeight": "700" }],
        "headline-lg": ["32px", { "lineHeight": "38px", "letterSpacing": "-0.02em", "fontWeight": "700" }],
        "body-sm": ["12px", { "lineHeight": "16px", "letterSpacing": "0.01em", "fontWeight": "500" }],
        "display": ["40px", { "lineHeight": "48px", "letterSpacing": "-0.03em", "fontWeight": "800" }],
        "body-md": ["14px", { "lineHeight": "20px", "letterSpacing": "0em", "fontWeight": "400" }],
        "price-row": ["20px", { "lineHeight": "24px", "letterSpacing": "-0.02em", "fontWeight": "700" }],
        "body-lg": ["16px", { "lineHeight": "24px", "letterSpacing": "-0.005em", "fontWeight": "400" }]
      }
    },
  },
}
