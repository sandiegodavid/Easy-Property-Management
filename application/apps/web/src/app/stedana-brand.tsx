const logos = {
  operator: {
    light: new URL("../assets/brand/stedana-logo-light.png", import.meta.url).href,
    dark: new URL("../assets/brand/stedana-logo-dark.png", import.meta.url).href,
    alt: "Stedana",
    height: 225,
  },
  login: {
    light: new URL("../assets/brand/stedana-owner-logo-light.png", import.meta.url).href,
    dark: new URL("../assets/brand/stedana-owner-logo-dark.png", import.meta.url).href,
    alt: "Stedana: property management for small portfolios and their owners",
    height: 252,
  },
};

export function StedanaBrand({ variant }: { variant: keyof typeof logos }) {
  const logo = logos[variant];
  return (
    <>
      <img
        className="workspace-brand workspace-brand-light"
        src={logo.light}
        alt={logo.alt}
        width="800"
        height={logo.height}
      />
      <img
        className="workspace-brand workspace-brand-dark"
        src={logo.dark}
        alt={logo.alt}
        width="800"
        height={logo.height}
      />
    </>
  );
}
