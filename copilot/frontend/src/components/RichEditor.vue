<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Picture,
  Upload,
  List,
} from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: string
  placeholder?: string
  minHeight?: number
  maxHeight?: number
  tip?: string
  showToolbar?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const editorRef = ref<HTMLDivElement | null>(null)
const isFocused = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

function onInput() {
  emit('update:modelValue', editorRef.value?.innerHTML || '')
}

function exec(command: string, value: string | undefined = undefined) {
  document.execCommand(command, false, value)
  editorRef.value?.focus()
  onInput()
}

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function linkifyText(text: string) {
  const escaped = escapeHtml(text)
  return escaped
    .replace(
      /(https?:\/\/[^\s<>"']+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
    )
    .replace(/\n/g, '<br>')
}

function insertHtml(html: string) {
  if (!html) return
  document.execCommand('insertHTML', false, html)
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function insertImage() {
  const url = window.prompt('请输入图片链接：')
  if (!url) return
  exec('insertImage', url)
}

function openImageFilePicker() {
  fileInputRef.value?.click()
}

async function onImageFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files
  if (!files || !files.length) return

  editorRef.value?.focus()
  for (const file of Array.from(files)) {
    if (!file.type.startsWith('image/')) {
      ElMessage.warning(`${file.name} 不是图片，已跳过`)
      continue
    }
    try {
      const dataUrl = await readFileAsDataUrl(file)
      insertHtml(`<p><img src="${dataUrl}" alt="${escapeHtml(file.name || 'uploaded-image')}" /></p>`)
    } catch {
      ElMessage.warning(`${file.name} 读取失败`)
    }
  }
  onInput()
  input.value = ''
}

async function onPaste(event: ClipboardEvent) {
  const clipboard = event.clipboardData
  if (!clipboard) {
    setTimeout(onInput, 0)
    return
  }

  const imageFiles = Array.from(clipboard.items)
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter((file): file is File => !!file)

  const html = clipboard.getData('text/html')
  const text = clipboard.getData('text/plain')

  if (!imageFiles.length) {
    if (!html && text && /https?:\/\/\S+/.test(text)) {
      event.preventDefault()
      insertHtml(linkifyText(text))
      onInput()
      return
    }
    setTimeout(onInput, 0)
    return
  }

  event.preventDefault()
  editorRef.value?.focus()
  insertHtml(html || linkifyText(text))

  try {
    for (const file of imageFiles) {
      const dataUrl = await readFileAsDataUrl(file)
      insertHtml(`<p><img src="${dataUrl}" alt="${escapeHtml(file.name || 'pasted-image')}" /></p>`)
    }
  } catch {
    ElMessage.warning('有图片没有粘贴成功，请单独拖入或重新截图粘贴')
  }
  onInput()
}

function onDrop(event: DragEvent) {
  // 允许拖拽图片进入编辑器，浏览器默认会插入 base64
  setTimeout(() => {
    onInput()
  }, 0)
}

watch(
  () => props.modelValue,
  (val) => {
    if (editorRef.value && editorRef.value.innerHTML !== val) {
      editorRef.value.innerHTML = val || ''
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="rich-editor" :class="{ focused: isFocused }">
    <div v-if="showToolbar !== false" class="editor-toolbar">
      <button type="button" class="tool-btn text-btn" title="加粗" @click="exec('bold')">B</button>
      <button type="button" class="tool-btn text-btn" title="斜体" @click="exec('italic')">I</button>
      <button type="button" class="tool-btn text-btn" title="下划线" @click="exec('underline')">U</button>
      <span class="toolbar-divider"></span>
      <button type="button" class="tool-btn" title="无序列表" @click="exec('insertUnorderedList')">
        <el-icon><List /></el-icon>
      </button>
      <span class="toolbar-divider"></span>
      <button type="button" class="tool-btn" title="插入图片链接" @click="insertImage">
        <el-icon><Picture /></el-icon>
      </button>
      <button type="button" class="tool-btn" title="上传本地图片" @click="openImageFilePicker">
        <el-icon><Upload /></el-icon>
      </button>
      <input
        ref="fileInputRef"
        type="file"
        accept="image/png,image/jpeg,image/jpg,image/webp,image/gif"
        style="display: none"
        @change="onImageFileSelected"
      />
    </div>
    <div
      ref="editorRef"
      class="editor-content"
      :style="{ minHeight: `${minHeight || 120}px`, maxHeight: `${maxHeight || 400}px` }"
      contenteditable="true"
      :data-placeholder="placeholder"
      @input="onInput"
      @paste="onPaste"
      @drop="onDrop"
      @focus="isFocused = true"
      @blur="isFocused = false"
    ></div>
    <div class="editor-tip">{{ tip || '提示：可直接粘贴文字、链接或截图，也可点击工具栏「上传本地图片」；图片会以 base64 临时嵌入，提交后自动转存。' }}</div>
  </div>
</template>

<style scoped lang="scss">
.rich-editor {
  border: 1px solid var(--border-color, #d0d5dd);
  border-radius: var(--radius-md, 12px);
  overflow: hidden;
  background: var(--surface-primary, #fff);
  transition: border-color 0.2s, box-shadow 0.2s;

  &.focused {
    border-color: var(--brand-500, #0d5ff9);
    box-shadow: 0 0 0 3px rgba(13, 95, 249, 0.1);
  }
}

.editor-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color, #d0d5dd);
  background: var(--surface-secondary, #f9fafb);
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: var(--text-secondary, #667085);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--surface-primary, #fff);
    color: var(--brand-500, #0d5ff9);
  }

  &.text-btn {
    font-weight: 700;
    font-size: 13px;
  }
}

.toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--border-color, #d0d5dd);
  margin: 0 4px;
}

.editor-content {
  overflow: auto;
  padding: 12px;
  font-size: var(--font-size-base, 14px);
  line-height: 1.7;
  color: var(--text-primary, #1d2939);
  outline: none;

  &:empty::before {
    content: attr(data-placeholder);
    color: var(--text-tertiary, #98a2b3);
    pointer-events: none;
  }

  :deep(img) {
    max-width: 100%;
    max-height: 300px;
    border-radius: var(--radius-sm, 8px);
    display: block;
    margin: 8px 0;
  }

  :deep(p) {
    margin: 0 0 8px;
  }

  :deep(ul), :deep(ol) {
    margin: 0 0 8px;
    padding-left: 20px;
  }

  :deep(li) {
    margin-bottom: 4px;
  }
}

.editor-tip {
  padding: 6px 12px;
  font-size: var(--font-size-xs, 12px);
  color: var(--text-tertiary, #98a2b3);
  background: var(--surface-secondary, #f9fafb);
  border-top: 1px solid var(--border-color, #d0d5dd);
}
</style>
