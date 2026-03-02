/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        parchment: {
          50: '#fefcf3',
          100: '#fdf6e3',
          200: '#f5e6c8',
          300: '#e8d5a3',
          400: '#d4b978',
          500: '#c4a35d',
        },
        ink: {
          700: '#3d3d3d',
          800: '#2d2d2d',
          900: '#1a1a1a',
        },
        cinnabar: {
          400: '#c45a3c',
          500: '#a0422a',
          600: '#8b3626',
          700: '#6d2a1e',
        },
      },
      fontFamily: {
        serif: ['"Noto Serif SC"', '"Source Han Serif SC"', 'serif'],
        sans: ['"Noto Sans SC"', '"Source Han Sans SC"', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
