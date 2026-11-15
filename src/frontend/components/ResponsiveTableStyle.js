// Copyright 1999-2025. WebPros International GmbH. All rights reserved.

import { createElement } from 'react';

/**
 * Plesk UI Library's <List vertical={...}> renders `.pul-list__table--vertical`
 * as stacked cards when the container width drops below the breakpoint.
 *
 * By default, Plesk hardcodes `.pul-list__cell-actions` to `width: 28px; position: absolute; right: 16px; top: 12px;`
 * assuming only a single 28x28 icon button exists. When an extension adds multiple buttons
 * (e.g. reload + manage, or refresh + delete), the content overflows by 80px+ past the right edge,
 * forcing a horizontal scrollbar on `.pul-list__table-container` that shifts the card and clips
 * the domain name and row labels on mobile devices.
 *
 * This component normalizes vertical cards so:
 * 1. The actions cell is placed as a clean footer bar within the card (`position: static; width: 100%`).
 * 2. The title cell has full card width without clipping (`padding-right: 8px`).
 * 3. Text in cells breaks gracefully (`overflow-wrap: anywhere`).
 * 4. Cards fit 100% of the mobile viewport with zero horizontal overflow or scrollbars.
 * 5. On desktop (non-vertical tables), this style has zero effect.
 */
const responsiveListCss = `
  .pul-list__table-container {
    overflow-x: auto;
    max-width: 100%;
  }
  .pul-list__table--vertical {
    width: 100% !important;
    max-width: 100% !important;
  }
  .pul-list__table--vertical tr {
    box-sizing: border-box !important;
    max-width: 100% !important;
  }
  .pul-list__table--vertical .pul-list__cell-actions {
    position: static !important;
    width: 100% !important;
    height: auto !important;
    display: flex !important;
    justify-content: flex-end !important;
    padding: 8px 0 0 0 !important;
    border-top: 1px dashed var(--pul-color-border-subtler, #e5e5e5) !important;
    margin-top: 6px !important;
    box-sizing: border-box !important;
  }
  .pul-list__table--vertical .pul-list__cell-actions:has(.pul-list__cell-inner-content:empty) {
    display: none !important;
  }
  .pul-list__table--vertical .pul-list__cell-actions .pul-list__cell-inner-content {
    width: 100% !important;
    display: flex !important;
    justify-content: flex-end !important;
  }
  .pul-list__table--vertical .pul-list__cell-has-actions {
    padding-right: 8px !important;
    width: 100% !important;
    box-sizing: border-box !important;
    min-width: 0 !important;
  }
  .pul-list__table--vertical .pul-list__cell-inner-title {
    flex-shrink: 0;
    padding-right: 8px;
  }
  .pul-list__table--vertical .pul-list__cell-inner-content {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
`;

export const ResponsiveTableStyle = () => (
    <style>{responsiveListCss}</style>
);

export default ResponsiveTableStyle;
