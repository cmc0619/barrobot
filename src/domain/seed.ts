import type { Recipe, StateDocument } from "./model.js";

const SEED_RECIPES: Recipe[] = [
  {
    id: "seed:gin-tonic",
    source: "seed",
    productProfile: "cocktail",
    name: "Gin and Tonic",
    imageUrl: null,
    instructions: "Pour over ice and garnish with lime.",
    ingredients: [
      { name: "gin", amountMl: 45, originalMeasure: "45 ml", manual: false },
      { name: "tonic water", amountMl: 120, originalMeasure: "120 ml", manual: false },
      { name: "lime", amountMl: null, originalMeasure: "1 wedge", manual: true },
    ],
  },
  {
    id: "seed:rum-cola",
    source: "seed",
    productProfile: "cocktail",
    name: "Rum and Cola",
    imageUrl: null,
    instructions: "Pour over ice and stir.",
    ingredients: [
      { name: "rum", amountMl: 45, originalMeasure: "45 ml", manual: false },
      { name: "cola", amountMl: 120, originalMeasure: "120 ml", manual: false },
    ],
  },
  {
    id: "seed:screwdriver",
    source: "seed",
    productProfile: "cocktail",
    name: "Screwdriver",
    imageUrl: null,
    instructions: "Pour over ice and stir.",
    ingredients: [
      { name: "vodka", amountMl: 45, originalMeasure: "45 ml", manual: false },
      { name: "orange juice", amountMl: 90, originalMeasure: "90 ml", manual: false },
    ],
  },
  {
    id: "seed:martini",
    source: "seed",
    productProfile: "cocktail",
    name: "Dry Martini",
    imageUrl: null,
    instructions: "Stir with ice, strain, and garnish.",
    ingredients: [
      { name: "gin", amountMl: 60, originalMeasure: "60 ml", manual: false },
      { name: "dry vermouth", amountMl: 10, originalMeasure: "10 ml", manual: false },
      { name: "lemon twist", amountMl: null, originalMeasure: "1 twist", manual: true },
    ],
  },
];

const SLUSHIE_RECIPES: Recipe[] = [
  {
    id: "seed:strawberry-lemonade-slush",
    source: "seed",
    productProfile: "slushie",
    name: "Strawberry Lemonade Slush",
    imageUrl: null,
    instructions: "Fill the cup with slush base, then add the selected flavours.",
    ingredients: [
      { name: "lemonade mix", amountMl: 90, originalMeasure: "90 ml", manual: false },
      { name: "strawberry syrup", amountMl: 30, originalMeasure: "30 ml", manual: false },
    ],
  },
  {
    id: "seed:blue-raspberry-slush",
    source: "seed",
    productProfile: "slushie",
    name: "Blue Raspberry Slush",
    imageUrl: null,
    instructions: "Fill the cup with slush base, then add the selected flavour.",
    ingredients: [
      { name: "blue raspberry syrup", amountMl: 45, originalMeasure: "45 ml", manual: false },
    ],
  },
];

/** Creates the complete initial state for a new v3 installation. */
export function createDefaultState(): StateDocument {
  return {
    schemaVersion: 2,
    settings: {
      productProfile: "cocktail",
      cocktailDbApiKey: "1",
      motionSocket: "/run/barrobot/motion.sock",
      maxDoseErrorPercent: 20,
      listenHost: "127.0.0.1",
      listenPort: 5000,
      motionProfile: "gentle",
      motion: {
        minimumHalfPeriodUs: 1300,
        maximumHalfPeriodUs: 7000,
        rampSteps: 120,
        settleMs: 280,
        holdPosition: true,
      },
      completionSound: "chime",
    },
    inventory: [],
    recipes: structuredClone([...SEED_RECIPES, ...SLUSHIE_RECIPES]),
    jobs: [],
  };
}
