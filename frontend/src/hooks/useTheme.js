import { useState, useEffect } from 'react'

/**
 * Custom hook to manage theme preferences
 * Supports auto-detection based on system preference, or manual light/dark selection
 *
 * @returns {Object} Theme state and controls
 */
export function useTheme() {
  // Theme preference: 'auto', 'light', or 'dark'
  const [themePreference, setThemePreference] = useState(() => {
    const saved = localStorage.getItem('themePreference')
    return saved || 'auto'
  })

  // Actual applied theme: 'light' or 'dark'
  const [appliedTheme, setAppliedTheme] = useState('light')

  // Detect system preference
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

    const updateTheme = () => {
      if (themePreference === 'auto') {
        setAppliedTheme(mediaQuery.matches ? 'dark' : 'light')
      } else {
        setAppliedTheme(themePreference)
      }
    }

    // Initial theme application
    updateTheme()

    // Listen for system preference changes
    mediaQuery.addEventListener('change', updateTheme)

    return () => mediaQuery.removeEventListener('change', updateTheme)
  }, [themePreference])

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', appliedTheme)
  }, [appliedTheme])

  // Save preference to localStorage
  const setTheme = newPreference => {
    setThemePreference(newPreference)
    localStorage.setItem('themePreference', newPreference)
  }

  return {
    themePreference, // 'auto', 'light', or 'dark'
    appliedTheme, // 'light' or 'dark'
    setTheme,
  }
}
