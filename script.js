const menuToggle = document.querySelector(".menu-toggle");
const apiBaseUrl = (window.PNG_HUB_API_BASE_URL || "").replace(/\/+$/, "");

function apiUrl(path) {
  return `${apiBaseUrl}${path}`;
}
const navigation = document.querySelector(".navigation");
const interestForms = document.querySelectorAll(".interest-form");

document.querySelector("#current-year").textContent = new Date().getFullYear();

function addPublicCard(container, item, kind) {
  const card = document.createElement("article");
  card.className = "public-content-card";
  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  const profileLabels = {
    student: "Student",
    sponsor: "Sponsor",
    employer: "Employer",
    other: "Administrator / community",
  };
  eyebrow.textContent = kind === "profile" ? (profileLabels[item.role] || "Community") : kind;
  const title = document.createElement("h3");
  title.textContent = item.title;
  card.append(eyebrow, title);
  if (item.body) {
    const body = document.createElement("p");
    body.textContent = item.body;
    card.append(body);
  }
  if (item.author) {
    const author = document.createElement("p");
    author.className = "public-content-author";
    author.textContent = item.author;
    card.append(author);
  }
  if (kind === "media" && item.media_url) {
    if (item.media_kind === "image") {
      const image = document.createElement("img");
      image.src = item.media_url;
      image.alt = item.title;
      image.loading = "lazy";
      card.prepend(image);
    } else {
      const video = document.createElement("video");
      video.controls = true;
      video.preload = "metadata";
      video.src = item.media_url;
      video.setAttribute("aria-label", item.title);
      card.prepend(video);
    }
  }
  container.append(card);
}

function renderPublicGroup(container, items, kind, emptyMessage) {
  container.replaceChildren();
  if (items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "public-content-empty";
    empty.textContent = emptyMessage;
    container.append(empty);
    return;
  }
  for (const item of items) addPublicCard(container, item, kind);
}

function renderMediaSlideshow(container, items) {
  container.replaceChildren();
  if (items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "public-content-empty";
    empty.textContent = "Photos and videos will appear here when published with permission.";
    container.append(empty);
    return;
  }

  const imageItems = items.filter((item) => item.media_kind === "image" && item.media_url);
  const videoItems = items.filter((item) => item.media_kind !== "image" || !item.media_url);

  if (imageItems.length > 0) {
    const slideshow = document.createElement("div");
    slideshow.className = "media-slideshow";
    slideshow.setAttribute("aria-label", "Published photos");

    const viewport = document.createElement("div");
    viewport.className = "media-slideshow-viewport";
    const slides = imageItems.map((item, index) => {
      const slide = document.createElement("figure");
      slide.className = "media-slide";
      slide.hidden = index !== 0;
      slide.setAttribute("aria-label", `Photo ${index + 1} of ${imageItems.length}`);
      const image = document.createElement("img");
      image.src = item.media_url;
      image.alt = item.title;
      image.loading = index === 0 ? "eager" : "lazy";
      const caption = document.createElement("figcaption");
      caption.innerHTML = `<strong></strong><span></span>`;
      caption.querySelector("strong").textContent = item.title;
      caption.querySelector("span").textContent = item.body || item.author || "";
      slide.append(image, caption);
      viewport.append(slide);
      return slide;
    });

    let activeIndex = 0;
    const updateSlide = (nextIndex) => {
      activeIndex = (nextIndex + slides.length) % slides.length;
      slides.forEach((slide, index) => {
        slide.hidden = index !== activeIndex;
      });
      dots.forEach((dot, index) => {
        dot.classList.toggle("is-active", index === activeIndex);
        dot.setAttribute("aria-current", index === activeIndex ? "true" : "false");
      });
    };

    const controls = document.createElement("div");
    controls.className = "media-slideshow-controls";
    const previous = document.createElement("button");
    previous.type = "button";
    previous.className = "slideshow-control";
    previous.textContent = "Previous photo";
    previous.addEventListener("click", () => updateSlide(activeIndex - 1));
    const next = document.createElement("button");
    next.type = "button";
    next.className = "slideshow-control";
    next.textContent = "Next photo";
    next.addEventListener("click", () => updateSlide(activeIndex + 1));
    controls.append(previous, next);

    const dots = [];
    const indicators = document.createElement("div");
    indicators.className = "media-slideshow-indicators";
    indicators.setAttribute("aria-label", "Choose a photo");
    imageItems.forEach((item, index) => {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "slideshow-dot";
      dot.setAttribute("aria-label", `Show photo ${index + 1}: ${item.title}`);
      dot.setAttribute("aria-current", index === 0 ? "true" : "false");
      dot.addEventListener("click", () => updateSlide(index));
      indicators.append(dot);
      dots.push(dot);
    });

    slideshow.append(viewport, controls, indicators);
    container.append(slideshow);

    if (slides.length > 1 && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      let timer = window.setInterval(() => updateSlide(activeIndex + 1), 5000);
      const pause = () => window.clearInterval(timer);
      const resume = () => {
        pause();
        timer = window.setInterval(() => updateSlide(activeIndex + 1), 5000);
      };
      slideshow.addEventListener("mouseenter", pause);
      slideshow.addEventListener("mouseleave", resume);
      slideshow.addEventListener("focusin", pause);
      slideshow.addEventListener("focusout", (event) => {
        if (!slideshow.contains(event.relatedTarget)) resume();
      });
    }
  }

  for (const item of videoItems) addPublicCard(container, item, "media");
}

fetch(apiUrl("/api/content"))
  .then(async (response) => {
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error("The public content API returned a webpage instead of JSON.");
    }
    if (!response.ok) throw new Error("Could not load public updates.");
    return response.json();
  })
  .then(({ items }) => {
    renderPublicGroup(
      document.querySelector("#public-articles"),
      items.filter((item) => item.kind === "article"),
      "article",
      "News and stories will appear here when published.",
    );
    renderPublicGroup(
      document.querySelector("#public-announcements"),
      items.filter((item) => item.kind === "announcement"),
      "announcement",
      "There are no new announcements at this time.",
    );
    renderPublicGroup(
      document.querySelector("#public-profiles"),
      items.filter((item) => item.kind === "profile"),
      "profile",
      "Community profiles will appear here when shared with permission.",
    );
    renderMediaSlideshow(
      document.querySelector("#public-media"),
      items.filter((item) => item.kind === "media"),
    );
  })
  .catch((error) => {
    console.error("Could not load public hub content.", error);
    for (const selector of ["#public-articles", "#public-announcements", "#public-profiles", "#public-media"]) {
      const container = document.querySelector(selector);
      const message = document.createElement("p");
      message.className = "public-content-empty";
      message.textContent = "The latest content could not be loaded. Please try again later.";
      container.replaceChildren(message);
    }
  });

menuToggle.addEventListener("click", () => {
  const isExpanded = menuToggle.getAttribute("aria-expanded") === "true";
  menuToggle.setAttribute("aria-expanded", String(!isExpanded));
  navigation.classList.toggle("is-open", !isExpanded);
});

navigation.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    menuToggle.setAttribute("aria-expanded", "false");
    navigation.classList.remove("is-open");
  }
});

interestForms.forEach((interestForm) => interestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const feedback = interestForm.querySelector(".form-feedback");
  feedback.classList.remove("is-error");

  const formData = new FormData(interestForm);
  const submission = {
    name: formData.get("name").trim(),
    email: formData.get("email").trim(),
    role: formData.get("role"),
  };
  const submitButton = interestForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.setAttribute("aria-busy", "true");

  try {
    const response = await fetch(apiUrl("/api/interests"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(submission),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "The server could not save your details.");
    }

    feedback.textContent = "Thanks for reaching out! Your interest has been sent to PNG Student Care Hub.";
    interestForm.reset();
  } catch (error) {
    console.error("Could not send your interest to the hub server.", error);
    feedback.classList.add("is-error");
    feedback.textContent = error.message || "We couldn’t send your details. Please try again.";
  } finally {
    submitButton.disabled = false;
    submitButton.removeAttribute("aria-busy");
  }
}));
