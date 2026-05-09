// Selector registry. Each field has:
//   - primary: most stable selector (usually #id)
//   - fallbacks: ordered list of alternatives (DOM-shape, label-anchored, structural)
//   - type: drives parsing + validation
//   - label: human-readable text used by AI-like recovery (looks for nearby element)
//
// The extractor combines this static registry with a learned-fallbacks store
// (data/selector-stats.json). Learned > primary > static fallbacks, ranked by
// historical reliability score.
module.exports = {
  kpiVideos: {
    primary: '#kpiVideos',
    fallbacks: [
      '[data-kpi="videos"]',
      '.kpi-card-new:has(.kpi-label-new:text-is("Contenus")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Contenus',
  },
  kpiViews: {
    primary: '#kpiViews',
    fallbacks: [
      '[data-kpi="views"]',
      '.kpi-card-new:has(.kpi-label-new:text-is("Vues totales")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Vues totales',
  },
  kpiLikes: {
    primary: '#kpiLikes',
    fallbacks: [
      '[data-kpi="likes"]',
      '.kpi-card-new:has(.kpi-label-new:text-is("Likes")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Likes',
  },
  kpiComments: {
    primary: '#kpiComments',
    fallbacks: [
      '[data-kpi="comments"]',
      '.kpi-card-new:has(.kpi-label-new:text-is("Commentaires")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Commentaires',
  },
  kpiShares: {
    primary: '#kpiShares',
    fallbacks: [
      '[data-kpi="shares"]',
      '.kpi-card-new:has(.kpi-label-new:text-is("Partages")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Partages',
  },
  kpiEngagement: {
    primary: '#kpiEngagement',
    fallbacks: [
      '[data-kpi="engagement"]',
      ".kpi-card-new:has(.kpi-label-new:text-is(\"Taux d'engagement\")) .kpi-value-new",
    ],
    type: 'percent',
    label: "Taux d'engagement",
  },
  kpiActiveAccounts: {
    primary: '#kpiActiveAccounts',
    fallbacks: [
      '.kpi-card-new:has(.kpi-label-new:text-is("Comptes actifs")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Comptes actifs',
  },
  kpiAvgViews: {
    primary: '#kpiAvgViews',
    fallbacks: [
      '.kpi-card-new:has(.kpi-label-new:text-is("Moy. vues/vidéo")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Moy. vues/vidéo',
  },
  kpiFollowers: {
    primary: '#kpiFollowers',
    fallbacks: [
      '.kpi-card-new:has(.kpi-label-new:text-is("Followers")) .kpi-value-new',
    ],
    type: 'number',
    label: 'Followers',
  },
  kpiFollowerGain: {
    primary: '#kpiFollowerGain',
    fallbacks: [
      '.kpi-card-new:has(.kpi-label-new:text-is("Gain followers")) .kpi-value-new',
    ],
    type: 'signedNumber',
    label: 'Gain followers',
  },
  activityRows: {
    primary: '#accountActivityBody tr',
    fallbacks: [
      '.activity-table tbody tr',
      'table tr:has(.activity-account)',
    ],
    type: 'rowList',
    label: 'Activité des comptes',
  },
};
