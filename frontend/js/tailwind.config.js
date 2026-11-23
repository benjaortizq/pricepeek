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
tailwind.config = {
  darkMode: "class",
  theme: {
    extend: {
      "colors": {
        "on-tertiary": "#ffffff",
        "on-primary-fixed": "#261900",
        "on-background": "#1b1c1c",
        "outline-variant": "#d4c4ad",
        "secondary": "#5f5e5e",
        "on-tertiary-container": "#005d25",
        "outline": "#827561",
        "surface-container": "#efeded",
        "surface-dim": "#dbdad9",
        "inverse-surface": "#303031",
        "surface": "#fbf9f8",
        "secondary-fixed-dim": "#c8c6c5",
        "on-tertiary-fixed": "#002109",
        "primary": "#7b5800",
        "tertiary": "#006e2d",
        "on-secondary-fixed-variant": "#474646",
        "background": "#fbf9f8",
        "surface-container-lowest": "#ffffff",
        "secondary-container": "#e5e2e1",
        "on-secondary-container": "#656464",
        "surface-container-highest": "#e4e2e2",
        "on-secondary-fixed": "#1c1b1b",
        "primary-fixed-dim": "#fabc33",
        "on-surface-variant": "#504534",
        "tertiary-fixed-dim": "#62df7d",
        "surface-container-low": "#f5f3f3",
        "on-tertiary-fixed-variant": "#005320",
        "on-surface": "#1b1c1c",
        "inverse-primary": "#fabc33",
        "surface-container-high": "#e9e8e7",
        "on-primary-container": "#684a00",
        "on-error": "#ffffff",
        "surface-tint": "#7b5800",
        "on-error-container": "#93000a",
        "error": "#ba1a1a",
        "inverse-on-surface": "#f2f0f0",
        "error-container": "#ffdad6",
        "on-primary": "#ffffff",
        "on-secondary": "#ffffff",
        "primary-fixed": "#ffdea5",
        "on-primary-fixed-variant": "#5d4200",
        "tertiary-fixed": "#7ffc97",
        "secondary-fixed": "#e5e2e1",
        "tertiary-container": "#5dda79",
        "primary-container": "#f5b82e",
        "surface-variant": "#e4e2e2",
        "surface-bright": "#fbf9f8"
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
