"""Shared Streamlit layout, present on every route; no trading side effects."""

MOBILE_STYLE = '''<style>
/* jj-mobile-layout-v2: keep content inside the phone without disabling zoom. */
/* jj-refresh-no-dim: retain brightness during Streamlit's periodic rerenders.
   Only presentation changes; disabled controls and freshness checks stay intact. */
[data-testid="stElementContainer"][data-stale="true"] {
  opacity: 1 !important;
  transition: none !important;
}
@media (max-width: 700px) {
  html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
  html, body, #root, .stApp, [data-testid="stAppViewContainer"],
  [data-testid="stMain"] {max-width: 100% !important; min-width: 0 !important;}
  .stApp, [data-testid="stMain"] {overflow-x: clip;}
  [data-testid="stMainBlockContainer"], .block-container {
    width: 100% !important; max-width: 100% !important; min-width: 0 !important;
    padding: 4rem .75rem 3rem !important; box-sizing: border-box !important;
  }
  [data-testid="stHorizontalBlock"] {flex-direction: column !important; gap: .75rem !important;}
  [data-testid="stColumn"] {width: 100% !important; min-width: 0 !important; flex: 1 1 100% !important;}
  [data-testid="stVerticalBlock"], [data-testid="stElementContainer"],
  [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stLayoutWrapper"],
  [data-testid="stExpander"], [data-testid="stTabs"], [role="tabpanel"] {
    min-width: 0 !important; max-width: 100% !important; box-sizing: border-box;
  }
  [data-testid="stMarkdownContainer"], [data-testid="stAlert"],
  [data-testid="stCaptionContainer"], [data-testid="stMetricValue"] {
    min-width: 0; max-width: 100%; overflow-wrap: anywhere;
  }
  [data-testid="stTabs"] [role="tablist"] {
    max-width: 100%; min-width: 0; overflow-x: auto !important; flex-wrap: nowrap;
    -webkit-overflow-scrolling: touch;
  }
  [data-testid="stTabs"] [role="tab"] {flex-shrink: 0; white-space: nowrap;}
  [data-testid="stTable"], [data-testid="stDataFrame"],
  [data-testid="stMarkdownContainer"]:has(table), [data-testid="stCode"] {
    max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch;
  }
  [data-testid="stVegaLiteChart"], [data-testid="stImage"] {max-width: 100%; min-width: 0;}
  [data-testid="stMarkdownContainer"] img {max-width: 100%; height: auto;}
  /* Target actual controls/combobox text: styling the parent alone does not
     override BaseWeb's smaller text and Safari may zoom when focusing it. */
  input, textarea, select, [role="combobox"], [data-baseweb="select"],
  [data-baseweb="select"] [data-testid="stMarkdownContainer"],
  [data-baseweb="select"] > div, [data-baseweb="select"] span,
  [data-baseweb="popover"] [role="option"] {font-size: 16px !important;}
  [data-baseweb="select"], [data-baseweb="input"], [data-testid="stNumberInput"],
  [data-testid="stTextInput"], [data-testid="stTextArea"] {min-width: 0 !important; max-width: 100%;}
  [data-testid="stButton"] button, [data-testid="stLinkButton"] a {
    width: 100%; min-height: 44px; white-space: normal; overflow-wrap: anywhere;
  }
  .jj-dashboard-hero {min-height: 110px !important; padding: 1rem !important;}
  .jj-dashboard-hero .name {font-size: 1.8rem !important;}
  .jj-dashboard-hero .description {max-width: 100% !important;}
  .jj-status-grid, .jj-range-grid {min-width: 0;}
  .jj-status-card, .jj-range-card, .jj-card {min-width: 0; overflow-wrap: anywhere;}
  h2 {font-size: 1.4rem !important; line-height: 1.3 !important;}
}
</style>'''
