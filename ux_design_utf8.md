## UI Pro Max Search Results
**Domain:** ux | **Query:** dashboard map tracking animation
**Source:** ux-guidelines.csv | **Found:** 3 results

### Result 1
- **Category:** Spatial UI
- **Issue:** Gaze Hover
- **Platform:** VisionOS
- **Description:** Elements should respond to eye tracking before pinch
- **Do:** Scale/highlight element on look
- **Don't:** Static element until pinch
- **Code Example Good:** hoverEffect()
- **Code Example Bad:** onTap only
- **Severity:** High

### Result 2
- **Category:** Animation
- **Issue:** Continuous Animation
- **Platform:** All
- **Description:** Infinite animations are distracting
- **Do:** Use for loading indicators only
- **Don't:** Use for decorative elements
- **Code Example Good:** animate-spin on loader
- **Code Example Bad:** animate-bounce on icons
- **Severity:** Medium

### Result 3
- **Category:** Animation
- **Issue:** Reduced Motion
- **Platform:** All
- **Description:** Respect user's motion preferences
- **Do:** Check prefers-reduced-motion media query
- **Don't:** Ignore accessibility motion settings
- **Code Example Good:** @media (prefers-reduced-motion: reduce)
- **Code Example Bad:** No motion query check
- **Severity:** High

