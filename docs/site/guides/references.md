# Reference images

A reference image shows Claude what you are after: a photo, a concept drawing, a page of
measurements. Attach one to a single request, or pin it so it goes with every request.
You can also stand it in the scene as a guide for yourself.

## Attach an image

1. Click the image button at the right of the prompt box.
2. Pick a file in the file browser. It appears as a chip above the prompt box, with a small
   preview and its file name. Add one file at a time; click the button again for the next.
3. Write a prompt if you want one, then press **Send**.

```{figure} ../images/guides-references/attached.png
:alt: The Whittle sidebar with two chips above the prompt box, crate_front.png with a highlighted pin button beside it and crate_side.png without one. The prompt reads "Add a lid like the one in the reference drawings." The image button is at the right of the prompt box.

Two references ready to send. The pin button beside `crate_front.png` means it is pinned;
`crate_side.png` goes with the next request only.
```

Use **PNG, JPEG, WebP or GIF**. The file browser hides GIF files, because Blender counts
them as movies. To attach one, type its file name in the browser, or tick **Movie Files** in
the browser's filter menu (the funnel icon); converting it to PNG also works. The browser
lists other image types too, such as TIFF or EXR, and they get a chip and count as sent, but
Claude never receives them and nothing warns you. Convert those first.

A reference is enough to send on its own, with no prompt and no sketch: Claude is then told
to work from the images. It usually helps to say what the image is for, though, such as
"match the proportions" or "use this colour scheme". The file name reaches Claude too, so
you can name an image in your prompt: "the lid in `crate_side.png`".

You can add references while Claude is working. They wait for your next **Send**. An
amendment, a follow-up you send while Claude is working, carries only text and strokes (see
[Amend a running turn](prompting.md#amend-a-running-turn)).

## Pin a reference to every request

Pin an image when Claude should have it for the whole job, such as the concept drawing of
the model you are building. Pin it before you press **Send**: once a turn has finished, an
unpinned image is gone from the list, and you have to attach it again.

1. Click the chip.
2. Choose **Pin to Every Request**.

The chip gets a highlighted pin button. Click that button, or **Unpin** in the chip's menu,
to go back to the next request only.

```{figure} ../images/guides-references/chip-menu.png
:alt: A menu titled Reference with Unpin, Place Facing the View, Place Behind, Front, Place Behind, Right, Place Below, Top, Open Image and Remove.

The menu of a chip, here a pinned one. An unpinned chip has **Pin to Every Request** at the
top instead.
```

The other items:

- **Open Image** shows the image in an Image Editor.
- **Remove** takes the reference off the list. Your file is not touched.
- The four **Place** items are described under [](#place-a-reference-in-the-scene).

## What happens after a turn

A turn is one request and the work Claude does on it. When a turn finishes, its unpinned
references are done with and their chips go. Pinned ones stay. The message in the
conversation says how many went with the turn.

```{figure} ../images/guides-references/after-turn.png
:alt: The sidebar after a turn. The message reads "Add a lid like the one in the reference drawings." with "2 refs" under it. Only the crate_front.png chip, with its pin button, remains above an empty prompt box.

After the turn: both images were sent (**2 refs**), and only the pinned one is still
listed.
```

If a turn fails or you stop it, every chip stays, so you can send again.

**Edit & Resend** on a turn brings its references back as chips, from the copies that turn
kept, so it works even if the original file has moved. They come back unpinned, and an image
that is still listed is not added twice. See {doc}`History and branches <history>`.

References belong to the scene, not to a chat. If you start or switch chats, the chips stay
as they are, and a pinned image goes with the first request of the new chat too.
See {doc}`Chats <chats>`.

## What Claude receives

Each time you press **Send**, Whittle copies every listed reference into that request.
Claude gets the images at the start of the turn, alongside your prompt and any sketch.

- **The image.** Whittle sends the file unchanged, without cropping it. Large images are
  scaled down on the way to Claude, as described below.
- **Its name.** Spaces and unusual characters in the name become `_`.

An image you sent earlier usually stays in that chat's conversation, so Claude can still
refer back to it. Pin an image to be sure it is there for each request, and for new chats.

Claude treats words in an image as material to work from. It follows instructions written
in an image only when your own prompt tells it to.

Four things to weigh with large images, especially pinned ones:

- **Cost.** Every image is billed as input each time it is sent. See
  {doc}`API key and cost <api-key>`.
- **File size.** Each request keeps its own copy, and those copies are saved with the chat
  in the `.blend`. A big pinned image adds to the file on every turn. The
  [chat menu](chats.md#open-the-chat-menu) shows the size each chat adds.
- **Detail.** An image more than about 2000 pixels on its longer side is scaled down on the
  way to Claude, and one over about 500 KB is recompressed as a JPEG, so fine detail may be
  lost. If it cannot be read at all, Claude gets a note saying so in place of the image.
- **Total size.** The image files of one request can come to 180 MB, sketch views included.
  Over that, Send refuses with a message saying so and nothing is sent: remove a chip or
  attach a smaller copy. Under it, Anthropic's limit of 32 MB per request still applies, after
  the scaling above, which big images pass easily but many small ones may not. A turn that
  goes over it fails with `Images too big: send fewer or smaller`, and **Edit** takes
  **Retry**'s place, because the same images would fail the same way. Edit brings the request
  back, so you can send fewer or smaller references. The conversation's earlier images count
  too, so if the chat already holds many, start a new chat.

Reference images go to Anthropic with the turn, and stay in the `.blend` for anyone you
share it with. See {doc}`Privacy and safety <privacy>`.

## Place a reference in the scene

Placing stands the image in the scene, so you can compare your model with it. It is for
you: Claude gets a reference because it is attached, not because it is placed.

Click the chip and choose where it goes:

- **Place Facing the View** faces the current view, centred on what the view is looking at.
- **Place Behind, Front** stands behind the 3D cursor, as seen from the front.
- **Place Behind, Right** stands behind the 3D cursor, as seen from the right.
- **Place Below, Top** lies just under the 3D cursor, as seen from above.

Put the 3D cursor where the model meets the ground first. The two **Place Behind** items
stand the bottom edge of the image level with the cursor, centred on it from side to side,
one metre behind it.

```{figure} ../images/guides-references/placed.png
:alt: The 3D viewport with the crate and the 3D cursor in front of a large drawing of a crate with a lid. The bottom edge of the drawing rests on the floor grid, the same ground as the crate. The grid and a post behind the drawing show through it.

**Place Behind, Front**: the drawing stands one metre behind the 3D cursor, with its bottom
edge at the cursor's height, so it shares the crate's ground. The grid and the post behind it
show through.
```

The image is an ordinary Blender image empty, two metres along its longer side and half
transparent, named `Ref` and the file's name, in a collection called **Whittle References**.
Move and scale it as you would any empty. Ctrl+Z undoes the placing.

A placed image stays out of Whittle's way:

- It never becomes part of the [target](prompting.md#choose-the-target), the objects Claude
  edits, even when selected.
- It does not show in the renders Claude takes to check its work.
- Claude is told to leave the **Whittle References** collection alone.

It also stays when its chip goes, whether you removed the chip or a turn cleared it. Delete
the empty in the Outliner when you no longer need it.

## If an image cannot be found

Blender reports `reference image not found:` and the path when you press **Send**, and
nothing is sent. A chip keeps the path of your file, not the image, so this happens when the
file was moved or renamed, or when you open the `.blend` on another computer with a pinned
reference still listed. A chip whose file is missing shows a plain image icon in place of
its preview.

Click the chip, choose **Remove**, then attach the file again from where it is now.
