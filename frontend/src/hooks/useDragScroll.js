import { useCallback, useEffect, useState } from 'react'

const INTERACTIVE_SELECTOR = [
  'a',
  'button',
  'input',
  'textarea',
  'select',
  'label',
  '[role="button"]',
  '[data-drag-scroll-ignore]',
].join(',')

export function useDragScroll() {
  const [element, setElement] = useState(null)
  const ref = useCallback((node) => {
    setElement(node)
  }, [])

  useEffect(() => {
    if (!element) return undefined

    let pointerId = null
    let startX = 0
    let startY = 0
    let startLeft = 0
    let startTop = 0
    let isDragging = false

    const canScroll = () => (
      element.scrollHeight > element.clientHeight || element.scrollWidth > element.clientWidth
    )

    const endDrag = (event) => {
      if (pointerId !== null && event?.pointerId !== pointerId) return
      pointerId = null
      isDragging = false
      element.classList.remove('is-dragging')
      try {
        if (event?.pointerId !== undefined) element.releasePointerCapture(event.pointerId)
      } catch {
        // Pointer capture can already be released by the browser.
      }
    }

    const onPointerDown = (event) => {
      if (event.button !== undefined && event.button !== 0) return
      if (event.target.closest?.(INTERACTIVE_SELECTOR)) return
      if (!canScroll()) return

      pointerId = event.pointerId
      startX = event.clientX
      startY = event.clientY
      startLeft = element.scrollLeft
      startTop = element.scrollTop
      isDragging = false
      try {
        element.setPointerCapture(event.pointerId)
      } catch {
        // Some embedded browsers may not support capture for every pointer.
      }
    }

    const onPointerMove = (event) => {
      if (pointerId === null || event.pointerId !== pointerId) return

      const deltaX = event.clientX - startX
      const deltaY = event.clientY - startY
      if (!isDragging && Math.abs(deltaX) + Math.abs(deltaY) < 4) return

      isDragging = true
      element.classList.add('is-dragging')
      event.preventDefault()
      element.scrollLeft = startLeft - deltaX
      element.scrollTop = startTop - deltaY
    }

    element.addEventListener('pointerdown', onPointerDown)
    element.addEventListener('pointermove', onPointerMove, { passive: false })
    element.addEventListener('pointerup', endDrag)
    element.addEventListener('pointercancel', endDrag)
    element.addEventListener('lostpointercapture', endDrag)

    return () => {
      element.removeEventListener('pointerdown', onPointerDown)
      element.removeEventListener('pointermove', onPointerMove)
      element.removeEventListener('pointerup', endDrag)
      element.removeEventListener('pointercancel', endDrag)
      element.removeEventListener('lostpointercapture', endDrag)
    }
  }, [element])

  return ref
}
