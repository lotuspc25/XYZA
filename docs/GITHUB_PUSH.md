# GitHub Push Talimatı

```bash
git add .
git commit -m "Prepare XYZA v0.1.0 release"
git remote add origin https://github.com/<kullanici>/<repo>.git
git push -u origin main
```

Not: EXE ve diğer build çıktıları `.gitignore` kapsamındadır; release asset olarak GitHub Releases bölümünde paylaşın.
