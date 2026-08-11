globalThis.Dragram = {
  splitSentences(text) {
    return (text.match(/[^。]+(?:。|$)/g) || []).map((sentence) => sentence.trim()).filter(Boolean);
  },
};
