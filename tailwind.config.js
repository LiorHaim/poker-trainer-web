/** Mirrors the config that used to be inlined beside the CDN script tag. */
module.exports = {
  content: ["./static/index.html"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Bebas Neue", "sans-serif"],
        body: ["Plus Jakarta Sans", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
};
