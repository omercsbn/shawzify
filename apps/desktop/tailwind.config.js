/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Deep charcoal base, elevated surfaces, warm Shawzin amber accent.
        ink: {
          900: '#0B0B0D',
          850: '#0F0F12',
          800: '#141418',
          700: '#1B1B20',
          600: '#24242B',
          500: '#2F2F38',
          400: '#3D3D48',
        },
        amber: {
          DEFAULT: '#E8A84C',
          bright: '#F5C275',
          deep: '#B47C2E',
          glow: 'rgba(232, 168, 76, 0.14)',
        },
        cyan: {
          DEFAULT: '#5AC8D8',
          deep: '#2E8A98',
        },
        paper: {
          DEFAULT: '#EDEBE6',
          dim: '#A9A69F',
          faint: '#6E6B65',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Cascadia Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.08em' }],
      },
      borderRadius: { xl: '0.625rem', '2xl': '0.875rem' },
      transitionTimingFunction: { swift: 'cubic-bezier(0.22, 1, 0.36, 1)' },
    },
  },
  plugins: [],
};
