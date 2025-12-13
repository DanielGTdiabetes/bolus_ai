module.exports = {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: '#6EE7B7',
        secondary: '#6366F1',
      },
      boxShadow: {
        glass: '0 20px 50px rgba(0,0,0,0.15)',
      },
      backdropBlur: {
        xs: '2px'
      }
    },
  },
  plugins: [],
}
